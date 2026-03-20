#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画板管理模块：处理画板解析和节点查询
"""
import os
import json
import re
import sys

# 添加项目路径到 sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
# 查找 myvse 目录（可能在上级目录）
parent_dir = os.path.dirname(project_root)
myvse_site_packages = os.path.join(parent_dir, 'myvse', 'lib', 'python3.10', 'site-packages')
if os.path.exists(myvse_site_packages):
    sys.path.insert(0, myvse_site_packages)

from parse_feishu_board import parse_feishu_board, get_doc_blocks, find_board_blocks, extract_board_content, get_board_nodes
from magic_jam.feishu_tools.feishu_doc import FeishuDoc
import lark_oapi as lark


class BoardManager:
    """画板管理器"""
    
    def __init__(self, json_dir=None):
        """
        初始化画板管理器
        
        Args:
            json_dir: JSON文件存储目录，默认为magic-vido目录下的"boards"文件夹
        """
        if json_dir is None:
            # 默认使用magic-vido目录
            json_dir = os.path.dirname(os.path.abspath(__file__))
        # 创建专门的"boards"文件夹（英文）
        self.json_dir = os.path.join(json_dir, "boards")
        if not os.path.exists(self.json_dir):
            os.makedirs(self.json_dir, exist_ok=True)
        self.board_cache = {}  # 缓存已加载的画板数据
        
    def _sanitize_filename(self, text):
        """
        清理文件名，移除非法字符
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文件名
        """
        # 移除或替换非法字符
        safe_text = re.sub(r'[<>:"/\\|?*]', '_', text)
        # 移除前后空格
        safe_text = safe_text.strip()
        # 如果为空，使用默认名称
        if not safe_text:
            safe_text = "未命名"
        return safe_text
    
    def _get_doc_title(self, feishu_doc, doc_link):
        """
        获取文档标题
        
        Args:
            feishu_doc: FeishuDoc实例
            doc_link: 文档链接
            
        Returns:
            文档标题，如果失败返回None
        """
        try:
            doc_info = feishu_doc.get_doc_info(doc_link)
            # 从doc_info中提取标题
            title = None
            if isinstance(doc_info, dict) and doc_info:
                # get_doc_info返回格式：{doc_link: {"title": "...", ...}}
                # 先尝试直接获取title字段
                if "title" in doc_info:
                    title = doc_info["title"]
                else:
                    # 尝试从键值中获取（doc_info以链接为key）
                    # 规范化链接（移除查询参数）
                    normalized_link = doc_link.split("?")[0] if "?" in doc_link else doc_link
                    if normalized_link in doc_info:
                        title = doc_info[normalized_link].get("title")
                    elif doc_link in doc_info:
                        title = doc_info[doc_link].get("title")
                    else:
                        # 遍历所有key查找匹配的链接
                        for key, value in doc_info.items():
                            if isinstance(value, dict) and "title" in value:
                                # 检查key是否与doc_link匹配（忽略查询参数）
                                if normalized_link in key or doc_link in key:
                                    title = value["title"]
                                    break
            return title
        except Exception as e:
            print(f"获取文档标题失败: {e}")
            return None
    
    def parse_board_from_link(self, doc_link, section_title=None):
        """
        从飞书链接解析画板并保存为JSON
        
        Args:
            doc_link: 飞书文档链接
            section_title: 章节标题，如果为None则查找文档中所有画板
            
        Returns:
            dict: 包含board_token和保存的JSON文件路径
        """
        try:
            feishu_doc = FeishuDoc()
            feishu_doc.init_client()
            
            # 获取文档标题
            doc_title = self._get_doc_title(feishu_doc, doc_link)
            if not doc_title:
                doc_title = "未命名文档"
            
            # 获取文档块
            blocks = get_doc_blocks(doc_link)
            
            # 查找画板块（如果section_title为None，查找所有画板）
            board_blocks = find_board_blocks(blocks, section_title)
            
            if not board_blocks:
                if section_title:
                    return {"success": False, "message": f"未找到章节 '{section_title}' 下的画板内容"}
                else:
                    return {"success": False, "message": "文档中未找到任何画板内容"}
            
            # 提取第一个画板的内容
            board_content = extract_board_content(board_blocks[0], feishu_doc)
            board_token = board_content.get("content", {}).get("token", "")
            
            if not board_token:
                return {"success": False, "message": "未能获取画板token"}
            
            # 先获取画板节点以确定根节点名称
            nodes = get_board_nodes(feishu_doc, board_token)
            
            if not nodes:
                return {"success": False, "message": "未能获取画板节点，可能需要特殊权限"}
            
            # 构建节点结构以获取根节点名称
            board_data = self._build_node_structure(nodes)
            root_name = board_data.get("root_node", {}).get("name", "board")
            
            # 使用 文件名-根节点 格式命名JSON文件
            safe_doc_title = self._sanitize_filename(doc_title)
            safe_root_name = self._sanitize_filename(root_name)
            filename = f"{safe_doc_title}-{safe_root_name}"
            json_file = os.path.join(self.json_dir, f"{filename}.json")
            
            # 构建查询标识（文件名-根节点）
            query_key = f"{safe_doc_title}-{safe_root_name}"
            
            # 如果文件已存在，直接返回已解析的信息
            if os.path.exists(json_file):
                # 加载已有数据获取节点数量
                existing_data = self.load_board_data(json_file)
                node_count = len(existing_data.get("nodes", [])) if existing_data else 0
                
                return {
                    "success": True,
                    "message": "历史已解析并存档",
                    "board_token": board_token,
                    "json_file": json_file,
                    "root_node": root_name,
                    "doc_title": doc_title,
                    "query_key": query_key,  # 添加查询标识
                    "node_count": node_count,
                    "already_exists": True  # 标记为已存在
                }
            
            # 如果不存在，继续解析并保存
            board_data["board_token"] = board_token
            board_data["doc_title"] = doc_title  # 保存文档标题到JSON中
            board_data["query_key"] = query_key  # 保存查询标识到JSON中
            
            # 确保目录存在
            os.makedirs(os.path.dirname(json_file), exist_ok=True)
            
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(board_data, f, ensure_ascii=False, indent=2)
            
            # 缓存数据
            self.board_cache[json_file] = board_data
            
            return {
                "success": True,
                "message": f"画板解析成功",
                "board_token": board_token,
                "json_file": json_file,
                "root_node": board_data.get("root_node", {}).get("name", ""),
                "doc_title": doc_title,
                "query_key": query_key,  # 添加查询标识
                "node_count": len(board_data.get("nodes", [])),
                "already_exists": False  # 标记为新解析
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"解析画板时出错: {str(e)}"}
    
    def _build_node_structure(self, nodes):
        """
        构建节点结构
        
        Args:
            nodes: 画板节点列表
            
        Returns:
            dict: 包含root_node和nodes的结构
        """
        # 查找根节点（mind_map_root）
        root_node = None
        node_map = {}
        
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue
                
            # 检查是否是根节点
            if node.get("mind_map_root"):
                root_data = node.get("mind_map_root", {})
                root_node = {
                    "id": node_id,
                    "name": node.get("text", {}).get("text", "") if node.get("text") else "",
                    "parent_id": None,
                    "children": root_data.get("children", [])
                }
                node_map[node_id] = root_node
            elif node.get("mind_map_node"):
                # 普通节点
                mind_map_node = node.get("mind_map_node", {})
                node_info = {
                    "id": node_id,
                    "name": node.get("text", {}).get("text", "") if node.get("text") else "",
                    "parent_id": mind_map_node.get("parent_id"),
                    "children": mind_map_node.get("children", [])
                }
                node_map[node_id] = node_info
        
        # 如果没有找到mind_map_root，尝试查找parent_id为None的节点
        if not root_node:
            for node_id, node_info in node_map.items():
                if node_info.get("parent_id") is None:
                    root_node = node_info
                    break
        
        # 如果根节点的children为空，根据parent_id反向填充
        if root_node and not root_node.get("children"):
            root_id = root_node.get("id")
            root_children = []
            for node_id, node_info in node_map.items():
                if node_info.get("parent_id") == root_id:
                    root_children.append(node_id)
            root_node["children"] = root_children
        
        # 对于所有节点，如果children为空，根据parent_id反向填充
        for node_id, node_info in node_map.items():
            if not node_info.get("children"):
                parent_id = node_info.get("id")
                children = []
                for nid, ninfo in node_map.items():
                    if ninfo.get("parent_id") == parent_id:
                        children.append(nid)
                node_info["children"] = children
        
        # 构建nodes列表（排除root_node）
        nodes_list = []
        for node_id, node_info in node_map.items():
            if node_id != root_node.get("id"):
                nodes_list.append(node_info)
        
        return {
            "root_node": root_node,
            "nodes": nodes_list
        }
    
    def load_board_data(self, json_file=None, root_name=None, query_text=None):
        """
        加载画板JSON数据
        
        Args:
            json_file: JSON文件路径（可选）
            root_name: 根节点名称（可选，用于查找文件，已废弃，建议使用query_text）
            query_text: 查询文本，支持"文件名-根节点"格式（可选）
            
        Returns:
            dict: 画板数据，如果失败返回None
        """
        # 如果指定了json_file，直接加载
        if json_file:
            if json_file in self.board_cache:
                return self.board_cache[json_file]
            
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.board_cache[json_file] = data
                    return data
            return None
        
        # 如果指定了query_text，使用search_root_nodes查找
        if query_text:
            results = self.search_root_nodes(query_text)
            if results:
                json_file = results[0]["json_file"]
                if json_file in self.board_cache:
                    return self.board_cache[json_file]
                if os.path.exists(json_file):
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.board_cache[json_file] = data
                        return data
            return None
        
        # 如果指定了root_name（兼容旧代码）
        if root_name:
            # 尝试直接匹配文件名
            safe_name = self._sanitize_filename(root_name)
            json_file = os.path.join(self.json_dir, f"{safe_name}.json")
            
            if json_file in self.board_cache:
                return self.board_cache[json_file]
            
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.board_cache[json_file] = data
                    return data
            
            # 如果直接匹配失败，尝试搜索
            results = self.search_root_nodes(root_name)
            if results:
                json_file = results[0]["json_file"]
                if json_file in self.board_cache:
                    return self.board_cache[json_file]
                if os.path.exists(json_file):
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.board_cache[json_file] = data
                        return data
        
        return None
    
    def find_node_by_name(self, node_name, json_file=None, root_name=None):
        """
        根据节点名称查找节点（支持模糊匹配）
        
        Args:
            node_name: 节点名称
            json_file: JSON文件路径（可选）
            root_name: 根节点名称（可选）
            
        Returns:
            dict: 节点信息，如果未找到返回None
        """
        board_data = self.load_board_data(json_file, root_name)
        if not board_data:
            return None
        
        # 先检查根节点
        root_node = board_data.get("root_node", {})
        if root_node.get("name") == node_name or node_name in root_node.get("name", ""):
            return root_node
        
        # 检查所有节点
        nodes = board_data.get("nodes", [])
        for node in nodes:
            if node.get("name") == node_name or node_name in node.get("name", ""):
                return node
        
        return None
    
    def get_node_children(self, node_id, json_file=None, root_name=None):
        """
        获取节点的子节点列表
        
        Args:
            node_id: 节点ID
            json_file: JSON文件路径（可选）
            root_name: 根节点名称（可选）
            
        Returns:
            list: 子节点列表
        """
        board_data = self.load_board_data(json_file, root_name)
        if not board_data:
            return []
        
        # 查找节点
        node = None
        root_node = board_data.get("root_node", {})
        if root_node.get("id") == node_id:
            node = root_node
        else:
            nodes = board_data.get("nodes", [])
            for n in nodes:
                if n.get("id") == node_id:
                    node = n
                    break
        
        if not node:
            return []
        
        # 获取子节点ID列表
        children_ids = node.get("children", [])
        if not children_ids:
            return []
        
        # 查找子节点详细信息
        children_nodes = []
        all_nodes = [root_node] + board_data.get("nodes", [])
        
        for child_id in children_ids:
            for n in all_nodes:
                if n.get("id") == child_id:
                    children_nodes.append(n)
                    break
        
        return children_nodes
    
    def get_node_by_id(self, node_id, json_file=None, root_name=None):
        """
        根据节点ID获取节点信息
        
        Args:
            node_id: 节点ID
            json_file: JSON文件路径（可选）
            root_name: 根节点名称（可选）
            
        Returns:
            dict: 节点信息，如果未找到返回None
        """
        board_data = self.load_board_data(json_file, root_name)
        if not board_data:
            return None
        
        # 检查根节点
        root_node = board_data.get("root_node", {})
        if root_node.get("id") == node_id:
            return root_node
        
        # 检查所有节点
        nodes = board_data.get("nodes", [])
        for node in nodes:
            if node.get("id") == node_id:
                return node
        
        return None
    
    def search_root_nodes(self, query_text):
        """
        搜索根节点（支持文件名-根节点格式查询）
        只在"boards"文件夹中搜索
        
        Args:
            query_text: 查询文本，支持以下格式：
                - "文件名-根节点"（完整匹配）
                - "文件名"（部分匹配文件名）
                - "根节点"（部分匹配根节点）
            
        Returns:
            list: 匹配的根节点列表
        """
        results = []
        
        # 只在"boards"文件夹中搜索
        if not os.path.exists(self.json_dir):
            return results
        
        for filename in os.listdir(self.json_dir):
            if not filename.endswith('.json'):
                continue
            
            json_file = os.path.join(self.json_dir, filename)
            try:
                board_data = self.load_board_data(json_file)
                if not board_data:
                    continue
                
                root_node = board_data.get("root_node", {})
                root_name = root_node.get("name", "")
                
                # 从文件名中提取文档标题和根节点名称
                # 文件名格式：文档标题-根节点.json
                base_filename = filename[:-5]  # 去掉.json后缀
                if '-' in base_filename:
                    # 尝试分割文件名（最后一个-作为分隔符）
                    parts = base_filename.rsplit('-', 1)
                    if len(parts) == 2:
                        file_doc_title = parts[0]
                        file_root_name = parts[1]
                    else:
                        file_doc_title = base_filename
                        file_root_name = ""
                else:
                    file_doc_title = base_filename
                    file_root_name = ""
                
                # 匹配逻辑：
                # 1. 完整匹配：查询文本完全匹配文件名（去掉.json）
                # 2. 格式匹配：查询文本匹配"文件名-根节点"格式
                # 3. 部分匹配：查询文本包含在文件名或根节点名称中
                is_match = False
                
                # 检查完整文件名匹配
                if query_text == base_filename:
                    is_match = True
                # 检查"文件名-根节点"格式匹配
                elif '-' in query_text:
                    query_parts = query_text.rsplit('-', 1)
                    if len(query_parts) == 2:
                        query_doc_title = query_parts[0].strip()
                        query_root_name = query_parts[1].strip()
                        # 检查文档标题和根节点是否都匹配
                        if (query_doc_title in file_doc_title or file_doc_title in query_doc_title) and \
                           (query_root_name in root_name or root_name in query_root_name):
                            is_match = True
                # 部分匹配：检查查询文本是否在文件名或根节点名称中
                elif query_text in base_filename or query_text in root_name or \
                     file_doc_title in query_text or root_name in query_text:
                    is_match = True
                
                if is_match:
                    results.append({
                        "root_name": root_name,
                        "root_id": root_node.get("id"),
                        "json_file": json_file,
                        "node_count": len(board_data.get("nodes", [])),
                        "doc_title": file_doc_title  # 添加文档标题信息
                    })
            except Exception as e:
                print(f"加载JSON文件失败 {json_file}: {e}")
                continue
        
        return results
