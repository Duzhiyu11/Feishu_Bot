#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析VAS维测应用手册表格，构建JSON树结构
"""
import re
import json
import os
from collections import defaultdict


def parse_markdown_table(md_file_path):
    """
    解析markdown文件中的表格数据
    
    Args:
        md_file_path: markdown文件路径
        
    Returns:
        list: 表格行数据列表，每行是一个字典
    """
    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找表格（从第31行开始）
    lines = content.split('\n')
    table_start = -1
    for i, line in enumerate(lines):
        if '| 序号 | 维测方法 |' in line:
            table_start = i
            break
    
    if table_start == -1:
        raise ValueError("未找到表格")
    
    # 解析表头
    header_line = lines[table_start]
    headers = [h.strip() for h in header_line.split('|')[1:-1]]
    
    # 跳过分隔行
    data_start = table_start + 2
    
    rows = []
    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line or not line.startswith('|'):
            break
        
        # 解析行数据
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) != len(headers):
            continue
        
        row_dict = {}
        for j, header in enumerate(headers):
            row_dict[header] = cells[j] if j < len(cells) else ""
        
        rows.append(row_dict)
    
    return rows


def split_related_data(data_str):
    """
    分割相关数据字符串（使用<br>分隔）
    
    Args:
        data_str: 相关数据字符串
        
    Returns:
        list: 分割后的数据列表
    """
    if not data_str:
        return []
    
    # 使用<br>或<br/>分割
    parts = re.split(r'<br\s*/?>', data_str, flags=re.IGNORECASE)
    # 清理每个部分
    parts = [p.strip() for p in parts if p.strip()]
    return parts


def build_tree_structure(rows):
    """
    构建树形JSON结构
    
    结构：
    维持方法支持
    ├── 全阶段
    │   ├── 相关数据1
    │   │   └── [维测方法1, 维测方法2, ...]
    │   └── 相关数据2
    │       └── [维测方法3, ...]
    └── 开发阶段
        ├── 相关数据X
        │   └── [维测方法4, ...]
        └── ...
    
    Args:
        rows: 表格行数据列表
        
    Returns:
        dict: 树形结构
    """
    # 第一层：按应用周期分组
    # 第二层：按相关数据分组
    # 第三层：维测方法列表
    
    tree = {
        "name": "维持方法支持",
        "children": {}
    }
    
    # 遍历每一行数据
    for row in rows:
        method_name = row.get('维测方法', '').strip()
        related_data_str = row.get('相关数据', '').strip()
        cycle = row.get('应用周期', '').strip()
        
        if not method_name or not cycle:
            continue
        
        # 分割相关数据
        related_data_list = split_related_data(related_data_str)
        
        # 初始化周期节点
        if cycle not in tree["children"]:
            tree["children"][cycle] = {
                "name": cycle,
                "children": {}
            }
        
        # 为每个相关数据添加维测方法
        for data in related_data_list:
            if not data:
                continue
            
            # 初始化相关数据节点
            if data not in tree["children"][cycle]["children"]:
                tree["children"][cycle]["children"][data] = {
                    "name": data,
                    "methods": []
                }
            
            # 添加维测方法（如果不存在）
            if method_name not in tree["children"][cycle]["children"][data]["methods"]:
                tree["children"][cycle]["children"][data]["methods"].append(method_name)
    
    return tree


def convert_to_list_format(tree):
    """
    将字典格式转换为列表格式（更便于JSON序列化和前端使用）
    
    Args:
        tree: 字典格式的树结构
        
    Returns:
        dict: 列表格式的树结构
    """
    result = {
        "name": tree["name"],
        "children": []
    }
    
    # 遍历每个应用周期
    for cycle_name, cycle_node in tree["children"].items():
        cycle_item = {
            "name": cycle_name,
            "children": []
        }
        
        # 遍历每个相关数据
        for data_name, data_node in cycle_node["children"].items():
            data_item = {
                "name": data_name,
                "methods": data_node["methods"]
            }
            cycle_item["children"].append(data_item)
        
        result["children"].append(cycle_item)
    
    return result


def main():
    # 文件路径
    md_file = "/root/zhiyu.du/myvse/magic-vido/doc/VAS维测应用手册.md"
    output_file = "/root/zhiyu.du/myvse/magic-vido/doc/vas_method_tree.json"
    
    print("正在解析表格数据...")
    rows = parse_markdown_table(md_file)
    print(f"解析到 {len(rows)} 行数据")
    
    print("正在构建树结构...")
    tree = build_tree_structure(rows)
    
    print("正在转换为列表格式...")
    result = convert_to_list_format(tree)
    
    # 保存JSON文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"✅ JSON树结构已保存到: {output_file}")
    
    # 打印统计信息
    print("\n统计信息:")
    print(f"- 应用周期数量: {len(result['children'])}")
    for cycle in result['children']:
        print(f"  - {cycle['name']}: {len(cycle['children'])} 个相关数据")
        total_methods = sum(len(data['methods']) for data in cycle['children'])
        print(f"    - 共 {total_methods} 个维测方法关联")
    
    # 打印示例结构
    print("\n示例结构预览:")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1000] + "...")


if __name__ == "__main__":
    main()
