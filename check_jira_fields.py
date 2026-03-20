#!/usr/bin/env python3
"""
临时脚本：查看JIRA中所有字段，找到"Found Version"字段的信息
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 直接导入JiraTool，避免导入其他依赖
from magic_jam.tools.jira_tool import JiraTool

def find_found_version_field():
    """查找Found Version字段的信息"""
    jira_tool = JiraTool()
    
    print("正在获取所有JIRA字段...")
    all_fields = jira_tool.get_all_fields()
    
    print(f"\n总共找到 {len(all_fields)} 个字段\n")
    
    # 查找包含"Found"或"Version"的字段
    found_fields = []
    for field in all_fields:
        field_name = field.get("name", "")
        field_id = field.get("id", "")
        field_type = field.get("type", "")
        
        # 查找包含"Found"或"Version"的字段
        if "found" in field_name.lower() or "version" in field_name.lower():
            found_fields.append({
                "name": field_name,
                "id": field_id,
                "type": field_type
            })
    
    print("=" * 80)
    print("包含'Found'或'Version'的字段：")
    print("=" * 80)
    
    if found_fields:
        for field in found_fields:
            print(f"\n字段名: {field['name']}")
            print(f"字段ID: {field['id']}")
            print(f"字段类型: {field['type']}")
            print("-" * 80)
    else:
        print("未找到包含'Found'或'Version'的字段")
    
    # 特别查找"Found Version"
    print("\n" + "=" * 80)
    print("查找'Found Version'字段（精确匹配）：")
    print("=" * 80)
    
    exact_match = None
    for field in all_fields:
        field_name = field.get("name", "")
        if field_name == "Found Version":
            exact_match = {
                "name": field_name,
                "id": field.get("id", ""),
                "type": field.get("type", ""),
                "custom": field.get("custom", False),
                "searchable": field.get("searchable", False),
                "orderable": field.get("orderable", False),
                "navigable": field.get("navigable", False)
            }
            break
    
    if exact_match:
        print(f"\n✅ 找到'Found Version'字段！")
        print(f"字段名: {exact_match['name']}")
        print(f"字段ID: {exact_match['id']}")
        print(f"字段类型: {exact_match['type']}")
        print(f"是否自定义字段: {exact_match['custom']}")
        print(f"可搜索: {exact_match['searchable']}")
        print(f"可排序: {exact_match['orderable']}")
        print(f"可导航: {exact_match['navigable']}")
    else:
        print("\n❌ 未找到精确匹配'Found Version'的字段")
        print("\n尝试查找类似的字段名...")
        similar_fields = []
        for field in all_fields:
            field_name = field.get("name", "")
            if "found" in field_name.lower() and "version" in field_name.lower():
                similar_fields.append({
                    "name": field_name,
                    "id": field.get("id", ""),
                    "type": field.get("type", "")
                })
        
        if similar_fields:
            print("\n找到类似的字段：")
            for field in similar_fields:
                print(f"  - {field['name']} (ID: {field['id']}, 类型: {field['type']})")
        else:
            print("  未找到类似的字段")

if __name__ == "__main__":
    try:
        find_found_version_field()
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
