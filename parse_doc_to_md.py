#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析飞书文档为 Markdown 格式并保存到 doc 目录
"""
import sys
import os
import re
from datetime import datetime

# 添加项目路径到 sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(project_root)
myvse_site_packages = os.path.join(parent_dir, 'myvse', 'lib', 'python3.10', 'site-packages')
if os.path.exists(myvse_site_packages):
    sys.path.insert(0, myvse_site_packages)

from magic_jam.parser.feishu_parser import FeishuDocParser


def sanitize_filename(title):
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


def get_doc_title(parser, doc_link):
    """
    获取文档标题
    
    Args:
        parser: FeishuDocParser 实例
        doc_link: 文档链接
        
    Returns:
        文档标题
    """
    try:
        doc_info = parser.feishu_doc.get_doc_info(doc_link)
        title = None
        
        if isinstance(doc_info, dict) and doc_info:
            # 先尝试直接获取title字段
            if "title" in doc_info:
                title = doc_info["title"]
            else:
                # 尝试从键值中获取（doc_info以链接为key）
                normalized_link = doc_link.split("?")[0] if "?" in doc_link else doc_link
                if normalized_link in doc_info:
                    title = doc_info[normalized_link].get("title")
                elif doc_link in doc_info:
                    title = doc_info[doc_link].get("title")
                else:
                    # 遍历所有key查找匹配的链接
                    for key, value in doc_info.items():
                        if isinstance(value, dict) and "title" in value:
                            if normalized_link in key or doc_link in key:
                                title = value["title"]
                                break
        
        if not title:
            title = "未命名文档"
        
        return title
    except Exception as e:
        print(f"获取文档信息失败: {e}")
        import traceback
        traceback.print_exc()
        return "未命名文档"


def parse_feishu_doc_to_md(doc_link, output_dir=None, images=False):
    """
    解析飞书文档为 Markdown 格式并保存到指定目录
    
    Args:
        doc_link: 飞书文档链接
        output_dir: 输出目录（可选，默认为 magic-vido/doc）
        images: 是否解析图片（默认False）
        
    Returns:
        保存的文件路径，如果失败返回None
    """
    try:
        print(f"正在解析飞书文档: {doc_link}")
        
        # 创建解析器实例
        parser = FeishuDocParser()
        
        # 获取文档标题
        title = get_doc_title(parser, doc_link)
        print(f"文档标题: {title}")
        
        # 确定输出目录
        if output_dir is None:
            # 默认保存到 magic-vido/doc 目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, "doc")
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成文件名
        safe_title = sanitize_filename(title)
        output_file = os.path.join(output_dir, f"{safe_title}.md")
        
        # 解析文档内容
        print("正在解析文档内容...")
        md_content = parser.parser_doc(doc_link, images=images)
        
        if not md_content:
            print("错误: 未能获取文档内容")
            return None
        
        # 添加文档元信息到 markdown 顶部
        parse_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        md_with_meta = f"""# {title}

> 文档链接: {doc_link}  
> 解析时间: {parse_time}

---

{md_content}
"""
        
        # 保存到文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(md_with_meta)
        
        print(f"✅ 文档已成功解析并保存到: {output_file}")
        print(f"文档内容长度: {len(md_content)} 字符")
        
        return output_file
        
    except Exception as e:
        print(f"❌ 解析文档时出错: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # 从命令行参数获取链接
    if len(sys.argv) < 2:
        print("用法: python parse_doc_to_md.py <doc_link> [output_dir] [images]")
        print("示例: python parse_doc_to_md.py https://nio.feishu.cn/docx/xxx")
        sys.exit(1)
    
    doc_link = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    images = len(sys.argv) > 3 and sys.argv[3].lower() == "images"
    
    parse_feishu_doc_to_md(doc_link, output_dir, images)
