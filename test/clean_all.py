import mysql.connector
from mysql.connector import Error
import os
import glob
import shutil
from pathlib import Path


def clean_files():
    """删除指定目录和文件"""

   

    # 删除./rag_storage目录下所有文件
    rag_storage_path = "./rag_storage"
    
    if os.path.exists(rag_storage_path):
        try:
            # 删除目录及其所有内容
            shutil.rmtree(rag_storage_path)
            print(f"✓ 已删除目录: {rag_storage_path}")
        except Exception as e:
            print(f"✗ 删除目录 {rag_storage_path} 时出错: {e}")
    else:
        print(f"ℹ 目录不存在: {rag_storage_path}")

    # 删除./uploads目录下所有文件
    uploads_path = "./uploads"
    
    if os.path.exists(uploads_path):
        try:
            # 删除目录及其所有内容
            shutil.rmtree(uploads_path)
            print(f"✓ 已删除目录: {uploads_path}")
        except Exception as e:
            print(f"✗ 删除目录 {uploads_path} 时出错: {e}")
    else:
        print(f"ℹ 目录不存在: {uploads_path}")

    
    # 删除~/nex-agent-output目录下所有文件
    next_out_path = "~/nex-agent-output"
    next_out_path = str(Path(next_out_path).expanduser().resolve())
    if os.path.exists(next_out_path):
        try:
            # 删除目录及其所有内容
            shutil.rmtree(next_out_path)
            print(f"✓ 已删除目录: {next_out_path}")
        except Exception as e:
            print(f"✗ 删除目录 {next_out_path} 时出错: {e}")
    else:
        print(f"ℹ 目录不存在: {next_out_path}")


   


    
    # 删除当前目录下所有.db*文件
    try:
        db_files = glob.glob("./*.db*")
        deleted_count = 0
        
        for db_file in db_files:
            try:
                os.remove(db_file)
                print(f"✓ 已删除文件: {db_file}")
                deleted_count += 1
            except Exception as e:
                print(f"✗ 删除文件 {db_file} 时出错: {e}")
        
        if deleted_count == 0:
            print("ℹ 未找到任何 .db* 文件")
        else:
            print(f"✓ 共删除了 {deleted_count} 个 .db* 文件")
            
    except Exception as e:
        print(f"✗ 查找或删除 .db* 文件时出错: {e}")

def reset_database():
    """重置数据库"""
    config = {
    "host": "127.0.0.1",
    "user": "<USER>",
    "password": "<PASSWORD>",
    "database": "mcp_server"
}
    
    try:
        # 连接 MySQL
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        
        # 删除数据库
        cursor.execute("DROP DATABASE IF EXISTS mcp_server")
        print("数据库 mcp_server 删除成功")
        
        # 重新创建数据库
        # cursor.execute("CREATE DATABASE mcp_server CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        # print("数据库 mcp_server 重新创建成功")
        
        cursor.close()
        conn.close()
        
    except Error as e:
        print(f"数据库重置失败: {e}")

if __name__ == "__main__":
    reset_database()
    clean_files()