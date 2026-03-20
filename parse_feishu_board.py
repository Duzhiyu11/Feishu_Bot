#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析飞书文档中的画板（思维导图）内容
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


def find_board_blocks(blocks, section_title="RootCause分析"):
    """查找指定章节下的画板块
    
    Args:
        blocks: 文档块列表
        section_title: 章节标题，如果为None则查找所有画板
    """
    board_blocks = []
    in_target_section = False
    
    # 如果section_title为None，查找所有画板
    if section_title is None:
        for i, block in enumerate(blocks):
            block_type = block.get("block_type", 0)
            block_data = block.get("block", block)
            
            # 查找画板块
            if block_type == 43:  # board类型（画板）
                board_data = block_data.get("board", {})
                if not board_data and "board" in block:
                    board_data = block.get("board", {})
                if board_data:
                    print(f"找到画板块: block_id={block.get('block_id')}, token={board_data.get('token')}")
                    board_blocks.append(block)
            elif block_type == 50:  # mindnote类型（思维导图）
                print(f"找到mindnote块: block_id={block.get('block_id')}")
                board_blocks.append(block)
            elif "board" in str(block_data).lower() or ("board" in block and block.get("board")):
                print(f"找到可能的画板块 (block_type={block_type}): block_id={block.get('block_id')}")
                board_blocks.append(block)
        
        return board_blocks
    
    # 如果指定了section_title，查找该章节下的画板
    for i, block in enumerate(blocks):
        block_type = block.get("block_type", 0)
        # 注意：块数据可能在 block 字段中，也可能直接在顶层
        block_data = block.get("block", block)
        
        # 检查是否是标题块
        # block_type 2 = text (普通文本标题)
        # block_type 5 = heading3 (三级标题)
        # block_type 6 = heading4 (四级标题)
        text_content = ""
        if block_type == 2:  # 文本标题
            text_elements = block_data.get("text", {}).get("elements", [])
            for elem in text_elements:
                if elem.get("text_run"):
                    text_content += elem["text_run"].get("content", "")
        elif block_type == 5:  # heading3
            heading3_data = block_data.get("heading3", {})
            if not heading3_data and "heading3" in block:
                heading3_data = block.get("heading3", {})
            text_elements = heading3_data.get("elements", [])
            for elem in text_elements:
                if elem.get("text_run"):
                    text_content += elem["text_run"].get("content", "")
        elif block_type == 6:  # heading4
            heading4_data = block_data.get("heading4", {})
            if not heading4_data and "heading4" in block:
                heading4_data = block.get("heading4", {})
            text_elements = heading4_data.get("elements", [])
            for elem in text_elements:
                if elem.get("text_run"):
                    text_content += elem["text_run"].get("content", "")
        
        # 检查是否是我们目标章节
        if text_content and section_title in text_content:
            in_target_section = True
            print(f"找到目标章节: {text_content} (block_type={block_type}, index={i})")
            continue
        
        # 如果在目标章节中
        if in_target_section:
            # 检查是否遇到新的标题（说明目标章节结束）
            if block_type in [2, 5, 6] and text_content and section_title not in text_content:
                # 遇到新标题，目标章节结束
                print(f"遇到新标题 '{text_content}'，目标章节结束")
                break
            
            # 查找画板块
            # block_type 27 = image (图片)
            # block_type 43 = board (画板) - 这是飞书画板的类型
            # block_type 50 = mindnote (思维导图)
            if block_type == 43:  # board类型（画板）
                board_data = block_data.get("board", {})
                if not board_data and "board" in block:
                    board_data = block.get("board", {})
                if board_data:
                    print(f"找到画板块: block_id={block.get('block_id')}, token={board_data.get('token')}")
                    board_blocks.append(block)
            elif block_type == 50:  # mindnote类型（思维导图）
                print(f"找到mindnote块: block_id={block.get('block_id')}")
                board_blocks.append(block)
            elif "board" in str(block_data).lower() or ("board" in block and block.get("board")):
                print(f"找到可能的画板块 (block_type={block_type}): block_id={block.get('block_id')}")
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
        import traceback
        traceback.print_exc()
        return []


def extract_board_content(board_block, feishu_doc):
    """从画板块中提取内容"""
    block_type = board_block.get("block_type", 0)
    # 注意：块数据可能在 block 字段中，也可能直接在顶层
    block_data = board_block.get("block", board_block)
    block_id = board_block.get("block_id", "")
    
    result = {
        "block_type": block_type,
        "block_id": block_id,
        "content": {},
        "nodes": []
    }
    
    if block_type == 43:  # board类型（画板）
        # 尝试从不同位置获取board数据
        board_data = block_data.get("board", {})
        if not board_data and "board" in board_block:
            board_data = board_block.get("board", {})
        
        board_token = board_data.get("token", "")
        result["content"] = {
            "token": board_token,
            "width": board_data.get("width", 0),
            "height": board_data.get("height", 0),
        }
        
        if board_token:
            result["board_url"] = f"https://nio.feishu.cn/board/{board_token}"
            print(f"画板链接: {result['board_url']}")
            
            # 尝试获取画板节点内容
            print(f"正在获取画板节点内容...")
            nodes = get_board_nodes(feishu_doc, board_token)
            if nodes:
                print(f"成功获取 {len(nodes)} 个画板节点")
                result["nodes"] = nodes
            else:
                print("未能获取画板节点（可能需要特殊权限或API版本）")
            
    elif block_type == 50:  # mindnote类型（思维导图）
        mindnote_data = block_data.get("mindnote", {})
        if not mindnote_data and "mindnote" in board_block:
            mindnote_data = board_block.get("mindnote", {})
        result["content"] = mindnote_data
    else:
        # 其他类型，尝试提取所有数据
        result["content"] = block_data
    
    return result


def parse_nodes_to_markdown(nodes):
    """将画板节点转换为markdown格式"""
    if not nodes:
        return ""
    
    md = "### 画板节点内容\n\n"
    
    # 按节点类型分类
    mind_map_nodes = []
    text_nodes = []
    other_nodes = []
    
    for node in nodes:
        node_type = node.get("type", "")
        if node.get("mind_map") or node.get("mind_map_node") or node.get("mind_map_root"):
            mind_map_nodes.append(node)
        elif node.get("text"):
            text_nodes.append(node)
        else:
            other_nodes.append(node)
    
    # 处理思维导图节点
    if mind_map_nodes:
        md += "#### 思维导图节点\n\n"
        for i, node in enumerate(mind_map_nodes, 1):
            md += f"**节点 {i}**:\n"
            if node.get("mind_map_root"):
                root = node["mind_map_root"]
                md += f"- 类型: 根节点\n"
                md += f"- 布局: {root.get('layout', 'N/A')}\n"
                md += f"- 子节点: {len(root.get('children', []))} 个\n"
            elif node.get("mind_map_node"):
                mind_node = node["mind_map_node"]
                md += f"- 类型: 思维导图节点\n"
                md += f"- 父节点ID: {mind_node.get('parent_id', 'N/A')}\n"
                md += f"- 子节点: {len(mind_node.get('children', []))} 个\n"
            md += "\n"
    
    # 处理文本节点
    if text_nodes:
        md += "#### 文本节点\n\n"
        for i, node in enumerate(text_nodes, 1):
            text_data = node.get("text", {})
            md += f"**文本节点 {i}**:\n"
            # 提取文本内容
            elements = text_data.get("elements", [])
            text_content = ""
            for elem in elements:
                if elem.get("text_run"):
                    text_content += elem["text_run"].get("content", "")
            if text_content:
                md += f"- 内容: {text_content}\n"
            md += "\n"
    
    # 其他节点
    if other_nodes:
        md += "#### 其他节点\n\n"
        md += f"```json\n"
        md += json.dumps(other_nodes, ensure_ascii=False, indent=2)
        md += "\n```\n\n"
    
    # 完整的节点数据（用于调试）
    md += "#### 完整节点数据\n\n"
    md += f"```json\n"
    md += json.dumps(nodes, ensure_ascii=False, indent=2)
    md += "\n```\n\n"
    
    return md


def parse_board_to_markdown(board_content):
    """将画板内容转换为markdown格式"""
    md = ""
    
    block_type = board_content.get("block_type", 0)
    content = board_content.get("content", {})
    nodes = board_content.get("nodes", [])
    
    if block_type == 43:  # board类型
        board_token = content.get("token", "")
        board_url = board_content.get("board_url", "")
        width = content.get("width", 0)
        height = content.get("height", 0)
        
        md += f"### 画板信息\n\n"
        md += f"- **Token**: `{board_token}`\n"
        md += f"- **尺寸**: {width} × {height}\n"
        md += f"- **访问链接**: [点击查看画板]({board_url})\n\n"
        
        # 如果有节点数据，解析节点
        if nodes:
            md += parse_nodes_to_markdown(nodes)
        else:
            md += f"**注意**: 未能获取画板节点内容，可能需要特殊权限或API版本支持。\n\n"
        
    elif block_type == 50:  # mindnote类型
        md += f"### 思维导图\n\n"
        md += f"```json\n"
        md += json.dumps(content, ensure_ascii=False, indent=2)
        md += "\n```\n\n"
    else:
        md += f"### 块内容 (类型: {block_type})\n\n"
        md += f"```json\n"
        md += json.dumps(board_content, ensure_ascii=False, indent=2)
        md += "\n```\n\n"
    
    return md


def parse_feishu_board(doc_link, section_title="RootCause分析", output_file=None):
    """
    解析飞书文档中指定章节的画板内容
    
    Args:
        doc_link: 飞书文档链接
        section_title: 章节标题关键词
        output_file: 输出文件路径（可选）
    """
    try:
        print(f"正在获取文档块结构: {doc_link}")
        blocks = get_doc_blocks(doc_link)
        
        # 保存块结构用于调试
        debug_file = "doc_blocks.json"
        with open(debug_file, 'w', encoding='utf-8') as f:
            json.dump(blocks, f, ensure_ascii=False, indent=2)
        print(f"文档块结构已保存到: {debug_file} (共 {len(blocks)} 个块)")
        
        # 查找画板块
        print(f"\n正在查找章节 '{section_title}' 下的画板...")
        board_blocks = find_board_blocks(blocks, section_title)
        
        if not board_blocks:
            print(f"未找到章节 '{section_title}' 下的画板内容")
            print("\n提示：尝试查看 doc_raw_content.json 文件，了解文档结构")
            return None
        
        print(f"\n找到 {len(board_blocks)} 个画板块")
        
        # 提取画板内容
        feishu_doc = FeishuDoc()
        feishu_doc.init_client()
        all_board_content = []
        for i, board_block in enumerate(board_blocks):
            print(f"\n处理第 {i+1} 个画板块...")
            board_content = extract_board_content(board_block, feishu_doc)
            all_board_content.append(board_content)
        
        # 转换为markdown
        md_content = f"# {section_title} - 画板内容\n\n"
        md_content += f"> 文档链接: {doc_link}\n\n"
        
        for i, board_content in enumerate(all_board_content):
            md_content += f"## 画板 {i+1}\n\n"
            md_content += parse_board_to_markdown(board_content)
            md_content += "\n"
        
        # 保存结果
        if not output_file:
            safe_title = "".join(c for c in section_title if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_title = safe_title.replace(' ', '_')
            output_file = f"{safe_title}_board.md"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        print(f"\n✅ 画板内容已保存到: {output_file}")
        
        return output_file
        
    except Exception as e:
        print(f"❌ 解析画板时出错: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    default_link = "https://nio.feishu.cn/docx/FMOadpw3gokucCxNscKc1bcdnKe"
    
    doc_link = sys.argv[1] if len(sys.argv) > 1 else default_link
    section_title = sys.argv[2] if len(sys.argv) > 2 else "RootCause分析"
    output_file = sys.argv[3] if len(sys.argv) > 3 else None
    
    parse_feishu_board(doc_link, section_title, output_file)
