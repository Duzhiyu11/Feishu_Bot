#!/usr/bin/env python3
"""
获取JIRA项目中所有可用的状态选项
"""
import sys
from data_center.jira_notify import JiraNotify

def main():
    print("=" * 60)
    print("JIRA 状态选项查询工具")
    print("=" * 60)
    print()
    
    try:
        notify = JiraNotify()
        print(f"正在获取项目 'nt3vims' 的所有状态...")
        print()
        
        # 方法1：通过项目问题类型获取状态
        statuses = notify.get_all_jira_statuses("nt3vims")
        
        if statuses:
            print(f"✅ 找到 {len(statuses)} 个状态选项：")
            print()
            print("状态列表（按字母顺序）：")
            print("-" * 60)
            for i, status in enumerate(statuses, 1):
                # 判断是否需要引号（包含空格的状态）
                display_status = f'"{status}"' if ' ' in status else status
                print(f"{i:2d}. {display_status}")
            print("-" * 60)
            print()
            print("使用示例：")
            print('  status="Open"')
            print('  status="Open,In Progress"')
            print('  status="Done,Closed,Resolved"')
            print()
            
            # 输出常用状态
            common_statuses = ["Open", "In Progress", "Done", "Closed", "Resolved", "Discard"]
            print("常用状态（推荐）：")
            for status in common_statuses:
                if status in statuses:
                    display_status = f'"{status}"' if ' ' in status else status
                    print(f"  - {display_status}")
        else:
            print("⚠️  无法获取状态列表，使用默认状态：")
            default_statuses = ["Open", "In Progress", "Done", "Closed", "Resolved", "Discard", "To Do", "In Review", "Reopened"]
            for status in default_statuses:
                display_status = f'"{status}"' if ' ' in status else status
                print(f"  - {display_status}")
        
        print()
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
