#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档解析和管理模块
用于解析飞书文档为Markdown格式并保存到本地
"""
import os
import re
from datetime import datetime
from magic_jam.parser.feishu_parser import FeishuDocParser


class DocManager:
    def __init__(self, base_dir=None):
        """
        初始化文档管理器
        
        Args:
            base_dir: 文档保存的基础目录，默认为当前文件所在目录
        """
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = base_dir
        self.docs_dir = os.path.join(base_dir, "parsed_docs")
        self.parser = FeishuDocParser()
        
        # 确保文档目录存在
        os.makedirs(self.docs_dir, exist_ok=True)
    
    def _sanitize_filename(self, title):
        """
        清理文件名，移除非法字符
        
        Args:
            title: 文档标题
            
        Returns:
            清理后的文件名
        """
        # 移除或替换非法字符
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
        # 移除前后空格
        safe_title = safe_title.strip()
        # 如果为空，使用默认名称
        if not safe_title:
            safe_title = "未命名文档"
        return safe_title
    
    def parse_and_save_doc(self, doc_link, images=False):
        """
        解析飞书文档并保存为Markdown文件
        
        Args:
            doc_link: 飞书文档链接
            images: 是否解析图片（默认False）
            
        Returns:
            dict: 包含解析结果的字典
                - success: 是否成功
                - message: 消息
                - file_path: 保存的文件路径（如果成功）
                - title: 文档标题（如果成功）
        """
        try:
            # 获取文档信息（标题等）
            try:
                doc_info = self.parser.feishu_doc.get_doc_info(doc_link)
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
                
                if not title:
                    title = "未命名文档"
            except Exception as e:
                print(f"获取文档信息失败: {e}")
                import traceback
                traceback.print_exc()
                title = "未命名文档"
            
            # 检查文件是否已存在
            safe_title = self._sanitize_filename(title)
            file_path = os.path.join(self.docs_dir, f"{safe_title}.md")
            
            if os.path.exists(file_path):
                return {
                    "success": True,
                    "message": f"文档已存在: {file_path}",
                    "file_path": file_path,
                    "title": title,
                    "already_exists": True
                }
            
            # 解析文档内容
            print(f"正在解析飞书文档: {doc_link}")
            md_content = self.parser.parser_doc(doc_link, images=images)
            
            if not md_content:
                return {
                    "success": False,
                    "message": "未能获取文档内容"
                }
            
            # 添加文档元信息到 markdown 顶部
            parse_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            md_with_meta = f"""# {title}

> 文档链接: {doc_link}  
> 解析时间: {parse_time}

---

{md_content}
"""
            
            # 保存到文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(md_with_meta)
            
            print(f"✅ 文档已成功解析并保存到: {file_path}")
            print(f"文档内容长度: {len(md_content)} 字符")
            
            return {
                "success": True,
                "message": f"文档解析成功并保存到: {file_path}",
                "file_path": file_path,
                "title": title,
                "already_exists": False
            }
            
        except Exception as e:
            error_msg = f"解析文档时出错: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": error_msg
            }
    
    def get_doc_list(self):
        """
        获取已解析的文档列表
        
        Returns:
            list: 文档文件路径列表
        """
        if not os.path.exists(self.docs_dir):
            return []
        
        md_files = []
        for filename in os.listdir(self.docs_dir):
            if filename.endswith('.md'):
                md_files.append(os.path.join(self.docs_dir, filename))
        
        return sorted(md_files)
    
    def search_doc(self, keyword):
        """
        在已解析的文档中搜索关键词
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            list: 包含关键词的文档文件路径列表
        """
        matching_files = []
        doc_files = self.get_doc_list()
        
        for file_path in doc_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if keyword.lower() in content.lower():
                        matching_files.append(file_path)
            except Exception as e:
                print(f"读取文件失败 {file_path}: {e}")
        
        return matching_files
