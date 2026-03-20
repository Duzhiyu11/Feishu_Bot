#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析飞书文档中的画板，提取节点关系并导出为JSON
"""
import sys
import os
import json

# 添加项目路径到 sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
# 查找 myvse 目录（可能在上级目录）
parent_dir = os.path.dirname(project_root)
myvse_site_packages = os.path.join(parent_dir, 'myvse', 'lib', 'python3.10', 'site-packages')
if os.path.exists(myvse_site_packages):
    sys.path.insert(0, myvse_site_packages)

from magic_jam.feishu_tools.feishu_doc import FeishuDoc
import lark_oapi as lark


def get_doc_blocks(doc_link):
    """获取文档的所有块结构"""
    feishu_doc = FeishuDoc()
    feishu_doc.init_client()
    
    if doc_link.find("nio.feishu.cn/docx/") == -1:
        raise ValueError("只支持docx格式的文档")
    
    doc_token = doc_link.split("nio.feishu.cn/docx/")[-1].split("?")[0]
    
    # 获取文档的块列表
    from lark_oapi.api.docx.v1 import ListDocumentBlockRequest
    request = ListDocumentBlockRequest.builder() \
        .document_id(doc_token) \
        .page_size(500) \
        .build()
    
    response = feishu_doc.client.docx.v1.document_block.list(request)
    
    if not response.success():
        raise Exception(f"获取文档块列表失败: {response.msg}")
    
    blocks_data = json.loads(lark.JSON.marshal(response.data))
    return blocks_data.get("items", [])


def find_board_blocks(blocks, section_title=None):
    """查找文档中的画板块
    
    Args:
        blocks: 文档块列表
        section_title: 可选，指定章节标题（如果提供，只查找该章节下的画板）
    """
    board_blocks = []
    
    if section_title:
        # 如果指定了章节标题，查找该章节下的画板
        in_target_section = False
        
        for i, block in enumerate(blocks):
            block_type = block.get("block_type", 0)
            block_data = block.get("block", block)
            
            # 检查是否是标题块
            text_content = ""
            if block_type == 2:  # 文本标题
                text_elements = block_data.get("text", {}).get("elements", [])
                for elem in text_elements:
                    if elem.get("text_run"):
                        text_content += elem["text_run"].get("content", "")
            elif block_type == 5:  # heading3
                text_elements = block_data.get("heading3", {}).get("elements", [])
                for elem in text_elements:
                    if elem.get("text_run"):
                        text_content += elem["text_run"].get("content", "")
            elif block_type == 6:  # heading4
                text_elements = block_data.get("heading4", {}).get("elements", [])
                for elem in text_elements:
                    if elem.get("text_run"):
                        text_content += elem["text_run"].get("content", "")
            
            # 检查是否是我们目标章节
            if text_content and section_title in text_content:
                in_target_section = True
                continue
            
            # 如果在目标章节中
            if in_target_section:
                # 检查是否遇到新的标题（说明目标章节结束）
                if block_type in [2, 5, 6] and text_content and section_title not in text_content:
                    break
                
                # 查找画板块
                if block_type == 43:  # board类型（画板）
                    board_data = block_data.get("board", {})
                    if not board_data and "board" in block:
                        board_data = block.get("board", {})
                    if board_data:
                        board_blocks.append(block)
    else:
        # 如果没有指定章节，查找所有画板
        for block in blocks:
            block_type = block.get("block_type", 0)
            if block_type == 43:  # board类型（画板）
                board_data = block.get("block", block).get("board", {})
                if not board_data and "board" in block:
                    board_data = block.get("board", {})
                if board_data:
                    board_blocks.append(block)
    
    return board_blocks


def get_board_nodes(feishu_doc, board_token):
    """获取画板的所有节点"""
    try:
        from lark_oapi.api.board.v1 import ListWhiteboardNodeRequest
        request = ListWhiteboardNodeRequest.builder() \
            .whiteboard_id(board_token) \
            .build()
        
        response = feishu_doc.client.board.v1.whiteboard_node.list(request)
        
        if response.success():
            nodes_data = json.loads(lark.JSON.marshal(response.data))
            return nodes_data.get("nodes", [])
        else:
            print(f"获取画板节点失败: {response.msg}")
            return []
    except Exception as e:
        print(f"获取画板节点时出错: {e}")
        return []


def extract_mind_map_structure(nodes):
    """从节点列表中提取思维导图结构
    
    Args:
        nodes: 所有节点列表
        
    Returns:
        dict: {
            "root_node": {...},
            "nodes": [...]
        }
    """
    # 只保留 mind_map 类型的节点
    mind_map_nodes = [n for n in nodes if n.get("type") == "mind_map"]
    
    if not mind_map_nodes:
        return None
    
    # 查找根节点
    root_node = None
    for node in mind_map_nodes:
        if node.get("mind_map_root"):
            root_node = node
            break
    
    if not root_node:
        print("警告: 未找到根节点")
        return None
    
    # 提取根节点信息
    root_id = root_node.get("id")
    root_text = root_node.get("text", {}).get("text", "") if root_node.get("text") else ""
    
    # 获取根节点的子节点（从right_children, left_children等）
    root_children = []
    mind_map_root = root_node.get("mind_map_root", {})
    root_children.extend(mind_map_root.get("right_children", []))
    root_children.extend(mind_map_root.get("left_children", []))
    root_children.extend(mind_map_root.get("up_children", []))
    root_children.extend(mind_map_root.get("down_children", []))
    
    root_info = {
        "id": root_id,
        "name": root_text,
        "parent_id": None,
        "children": root_children
    }
    
    # 提取所有节点的信息
    nodes_info = []
    node_map = {}  # 用于快速查找节点
    
    for node in mind_map_nodes:
        node_id = node.get("id")
        node_text = node.get("text", {}).get("text", "") if node.get("text") else ""
        
        # 获取父节点和子节点
        parent_id = None
        children = []
        
        if node.get("mind_map_node"):
            mind_map_node = node.get("mind_map_node", {})
            parent_id = mind_map_node.get("parent_id")
            children = mind_map_node.get("children", [])
        
        node_info = {
            "id": node_id,
            "name": node_text,
            "parent_id": parent_id,
            "children": children
        }
        
        nodes_info.append(node_info)
        node_map[node_id] = node_info
    
    # 将根节点也添加到nodes_info中（如果还没有）
    if root_id not in node_map:
        nodes_info.append(root_info)
    
    return {
        "root_node": root_info,
        "nodes": nodes_info
    }


def parse_feishu_boards_to_json(doc_link, section_title=None, output_dir=None):
    """解析飞书文档中的画板，导出为JSON文件
    
    Args:
        doc_link: 飞书文档链接
        section_title: 可选，指定章节标题（如果提供，只解析该章节下的画板）
        output_dir: 输出目录，默认为当前目录
        
    Returns:
        list: 生成的JSON文件路径列表
    """
    try:
        print(f"正在获取文档块结构: {doc_link}")
        blocks = get_doc_blocks(doc_link)
        print(f"文档共有 {len(blocks)} 个块")
        
        # 查找画板块
        if section_title:
            print(f"\n正在查找章节 '{section_title}' 下的画板...")
        else:
            print(f"\n正在查找文档中的所有画板...")
        
        board_blocks = find_board_blocks(blocks, section_title)
        
        if not board_blocks:
            print(f"未找到画板")
            return []
        
        print(f"找到 {len(board_blocks)} 个画板块")
        
        # 初始化飞书客户端
        feishu_doc = FeishuDoc()
        feishu_doc.init_client()
        
        # 设置输出目录
        if not output_dir:
            output_dir = "."
        os.makedirs(output_dir, exist_ok=True)
        
        output_files = []
        
        # 处理每个画板
        for i, board_block in enumerate(board_blocks):
            print(f"\n处理第 {i+1} 个画板...")
            
            # 获取画板token
            board_data = board_block.get("block", board_block).get("board", {})
            if not board_data and "board" in board_block:
                board_data = board_block.get("board", {})
            
            board_token = board_data.get("token", "")
            if not board_token:
                print(f"  跳过：无法获取画板token")
                continue
            
            print(f"  画板Token: {board_token}")
            
            # 获取画板节点
            print(f"  正在获取画板节点...")
            nodes = get_board_nodes(feishu_doc, board_token)
            
            if not nodes:
                print(f"  跳过：未能获取节点")
                continue
            
            print(f"  获取到 {len(nodes)} 个节点")
            
            # 提取思维导图结构
            structure = extract_mind_map_structure(nodes)
            
            if not structure:
                print(f"  跳过：未能提取思维导图结构")
                continue
            
            # 获取根节点名称用于文件命名
            root_name = structure["root_node"]["name"]
            if not root_name:
                root_name = f"board_{i+1}"
            
            # 清理文件名（移除非法字符）
            safe_name = "".join(c for c in root_name if c.isalnum() or c in (' ', '-', '_', '（', '）', '(', ')')).strip()
            safe_name = safe_name.replace(' ', '_').replace('（', '_').replace('）', '_').replace('(', '_').replace(')', '_')
            if not safe_name:
                safe_name = f"board_{i+1}"
            
            # 构建输出JSON
            output_data = {
                "board_token": board_token,
                "root_node": structure["root_node"],
                "nodes": structure["nodes"]
            }
            
            # 保存JSON文件
            output_file = os.path.join(output_dir, f"{safe_name}.json")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            print(f"  ✅ 已保存到: {output_file}")
            print(f"  根节点: {root_name}")
            print(f"  节点总数: {len(structure['nodes'])}")
            
            output_files.append(output_file)
        
        return output_files
        
    except Exception as e:
        print(f"❌ 解析画板时出错: {e}")
        import traceback
        traceback.print_exc()
        return []


if __name__ == "__main__":
    default_link = "https://nio.feishu.cn/docx/FMOadpw3gokucCxNscKc1bcdnKe"
    
    doc_link = sys.argv[1] if len(sys.argv) > 1 else default_link
    section_title = sys.argv[2] if len(sys.argv) > 2 else None
    output_dir = sys.argv[3] if len(sys.argv) > 3 else None
    
    parse_feishu_boards_to_json(doc_link, section_title, output_dir)
