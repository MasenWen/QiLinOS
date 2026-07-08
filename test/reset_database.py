import mysql.connector
from mysql.connector import Error

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