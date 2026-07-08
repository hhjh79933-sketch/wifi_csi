import os

from flask import Flask, request, jsonify
from flask_cors import CORS

import pymysql
import pymysql.cursors
import bcrypt
import jwt
import datetime

app = Flask(__name__)

CORS(app)

SECRET_KEY = os.environ.get("SECRET_KEY", "your_secret_key")

# =========================
# 数据库连接（每次请求新建，避免超时断开）
# =========================

def get_db():
    """每次调用创建新连接，避免全局连接超时"""
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        user=os.environ.get("DB_USER", "esp_admin"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "esp_admin"),
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor
    )

# =========================
# 测试接口
# =========================

@app.route('/')
def home():
    return "Flask server is running!"

# =========================
# 注册
# =========================

@app.route('/register', methods=['POST'])
def register():

    data = request.json

    username = data.get("username")
    password = data.get("password")

    if not username or not password:

        return jsonify({
            "status": "error",
            "message": "用户名或密码不能为空"
        })

    db = get_db()
    cursor = db.cursor()

    try:
        # 检查用户名
        sql_check = "SELECT * FROM users WHERE username=%s"
        cursor.execute(sql_check, (username,))

        if cursor.fetchone():

            return jsonify({
                "status": "error",
                "message": "用户名已存在"
            })

        # 密码加密
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

        # 插入数据库
        sql_insert = """
            INSERT INTO users
            (username, password_hash, is_admin, created_at)
            VALUES (%s, %s, %s, %s)
        """

        cursor.execute(sql_insert, (
            username,
            password_hash,
            0,
            datetime.datetime.now()
        ))

        db.commit()

        return jsonify({
            "status": "success",
            "message": "注册成功"
        })
    finally:
        cursor.close()
        db.close()

# =========================
# 登录
# =========================

@app.route('/login', methods=['POST'])
def login():

    data = request.json

    username = data.get("username")
    password = data.get("password")

    db = get_db()
    cursor = db.cursor()

    try:
        sql = "SELECT * FROM users WHERE username=%s"
        cursor.execute(sql, (username,))
        user = cursor.fetchone()

        if not user:

            return jsonify({
                "status": "error",
                "message": "用户不存在"
            })

        # 验证密码
        if not bcrypt.checkpw(
            password.encode('utf-8'),
            user['password_hash'].encode('utf-8')
        ):

            return jsonify({
                "status": "error",
                "message": "密码错误"
            })

        # JWT Token
        token = jwt.encode({

            "user_id": user["id"],
            "username": user["username"],
            "is_admin": user["is_admin"],

            "exp": datetime.datetime.utcnow()
                   + datetime.timedelta(days=1)

        }, SECRET_KEY, algorithm="HS256")

        return jsonify({

            "status": "success",

            "token": token,

            "username": user["username"],

            "is_admin": user["is_admin"]
        })
    finally:
        cursor.close()
        db.close()

# =========================
# NFC 绑定
# =========================

@app.route('/bind_nfc', methods=['POST'])
def bind_nfc():

    db = get_db()
    cursor = db.cursor()

    try:

        data = request.json

        username = data.get("username")
        uid = data.get("uid")

        print("收到绑定请求")
        print("username =", username)
        print("uid =", uid)

        # 查询用户信息
        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        user = cursor.fetchone()

        if user is None:
            return jsonify({
                "success": False,
                "message": "用户不存在"
            })

        user_id = user['id']

        # 查询 NFC
        sql = """
        SELECT area_id
        FROM nfc_tags
        WHERE uid=%s
        AND is_active=1
        """

        cursor.execute(sql, (uid,))

        result = cursor.fetchone()

        print("NFC查询结果 =", result)

        if result is None:

            return jsonify({
                "success": False,
                "message": "该NFC未注册"
            })

        area_id = result['area_id']

        # 查询区域名字
        cursor.execute(
            "SELECT name FROM areas WHERE id=%s",
            (area_id,)
        )

        area = cursor.fetchone()

        print("区域查询结果 =", area)

        if area is None:

            return jsonify({
                "success": False,
                "message": "区域不存在"
            })

        area_name = area['name']

        cursor.execute(
            """
            UPDATE users
            SET current_area_id=%s
            WHERE username=%s
            """,
            (
                area_id,
                username
            )
        )

        # 记录用户绑定历史
        cursor.execute(
            """
            INSERT INTO user_area_assignments
            (
                user_id,
                area_id,
                assigned_by,
                created_at
            )
            VALUES
            (
                %s,
                %s,
                %s,
                NOW()
            )
            """,
            (
                user_id,
                area_id,
                username
            )
        )

        db.commit()

        return jsonify({
            "success": True,
            "message": f"成功绑定 {area_name}",
            "area_name": area_name
        })

    except Exception as e:

        print("bind_nfc错误 =", str(e))

        return jsonify({
            "success": False,
            "message": "服务器异常"
        })
    finally:
        cursor.close()
        db.close()

@app.route('/unbind_nfc', methods=['POST'])
def unbind_nfc():

    db = get_db()
    cursor = db.cursor()

    try:

        data = request.json

        username = data.get("username")

        # 查询用户
        cursor.execute(
            """
            SELECT id,current_area_id
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        user = cursor.fetchone()

        if user is None:

            return jsonify({
                "success": False,
                "message": "用户不存在"
            })

        area_id = user['current_area_id']

        if area_id is None:

            return jsonify({
                "success": False,
                "message": "当前未绑定区域"
            })

        # 用户当前区域置空
        cursor.execute(
            """
            UPDATE users
            SET current_area_id=NULL
            WHERE username=%s
            """,
            (username,)
        )

        db.commit()

        return jsonify({
            "success": True,
            "message": "解绑成功"
        })

    except Exception as e:

        print("unbind_nfc错误=", e)

        return jsonify({
            "success": False,
            "message": "服务器异常"
        })
    finally:
        cursor.close()
        db.close()

@app.route('/get_current_area')
def get_current_area():

    username = request.args.get("username")

    print("查询用户 =", username)

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            """
            SELECT a.name
            FROM users u
            LEFT JOIN areas a
            ON u.current_area_id=a.id
            WHERE u.username=%s
            """,
            (username,)
        )

        result = cursor.fetchone()

        print("查询结果 =", result)

        if result is None or result['name'] is None:

            return jsonify({
                "success": False
            })

        area_name = result['name']

        print("area_name =", area_name)

        return jsonify({
            "success": True,
            "area_name": area_name
        })
    finally:
        cursor.close()
        db.close()

# =========================
# 获取告警
# =========================

@app.route('/get_alerts')
def get_alerts():

    db = get_db()
    cursor = db.cursor()

    try:

        username = request.args.get("username")

        # 查询用户当前区域
        cursor.execute(
            """
            SELECT current_area_id
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        user = cursor.fetchone()

        if user is None:

            return jsonify({
                "success": False
            })

        area_id = user['current_area_id']

        if area_id is None:

            return jsonify([])

        # 查询区域名
        cursor.execute(
            """
            SELECT name
            FROM areas
            WHERE id=%s
            """,
            (area_id,)
        )

        area = cursor.fetchone()

        area_name = area['name']

        # 查询该区域绑定的设备
        cursor.execute(
            """
            SELECT device_id
            FROM device_area_bindings
            WHERE area_id=%s
            AND effective_to IS NULL
            """,
            (area_id,)
        )

        device_ids = [row['device_id'] for row in cursor.fetchall()]

        if not device_ids:
            return jsonify([])

        # 查询最近跌倒事件（来自该区域所有设备）
        placeholders = ",".join(["%s"] * len(device_ids))
        cursor.execute(
            f"""
            SELECT
            id,
            created_at,
            state,
            note
            FROM events
            WHERE device_id IN ({placeholders})
            AND type='csi_evt'
            ORDER BY created_at DESC
            LIMIT 20
            """,
            device_ids
        )

        rows = cursor.fetchall()

        result = []

        for row in rows:

            result.append({

                "id": row['id'],

                "group_id": str(area_id),

                "room": area_name,

                "message": "检测到跌倒事件",

                "time": row['created_at'].strftime("%Y-%m-%d %H:%M:%S"),

                "state": row['state'],
                "note": row.get('note') or ""

            })

        print("返回事件数量=", len(result))

        if len(result) > 0:
            print("最新事件=", result[0])

        return jsonify(result)

    except Exception as e:

        print("get_alerts错误=", e)

        return jsonify([])
    finally:
        cursor.close()
        db.close()

@app.route('/verify_password', methods=['POST'])
def verify_password():

    data = request.json

    username = data.get("username")
    password = data.get("password")

    db = get_db()
    cursor = db.cursor()

    try:
        sql = "SELECT * FROM users WHERE username=%s"
        cursor.execute(sql, (username,))
        user = cursor.fetchone()

        if not user:

            return jsonify({
                "success": False,
                "message": "用户不存在"
            })

        if not bcrypt.checkpw(
                password.encode("utf-8"),
                user["password_hash"].encode("utf-8")
        ):

            return jsonify({
                "success": False,
                "message": "原密码错误"
            })

        return jsonify({
            "success": True,
            "message": "验证成功"
        })
    finally:
        cursor.close()
        db.close()

@app.route('/change_password', methods=['POST'])
def change_password():

    data = request.json

    username = data.get("username")
    new_password = data.get("new_password")

    db = get_db()
    cursor = db.cursor()

    try:
        sql = "SELECT * FROM users WHERE username=%s"
        cursor.execute(sql, (username,))
        user = cursor.fetchone()

        if not user:

            return jsonify({
                "success": False,
                "message": "用户不存在"
            })

        # bcrypt加密新密码
        password_hash = bcrypt.hashpw(
            new_password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        cursor.execute(
            """
            UPDATE users
            SET password_hash=%s
            WHERE username=%s
            """,
            (password_hash, username)
        )

        db.commit()

        return jsonify({
            "success": True,
            "message": "密码修改成功"
        })
    finally:
        cursor.close()
        db.close()

@app.route("/update_alert_state", methods=["POST"])
def update_alert_state():

    db = get_db()
    cursor = db.cursor()

    try:

        data = request.json

        alert_id = data.get("id")
        state = data.get("state")

        cursor.execute(
            """
            UPDATE events
            SET state=%s
            WHERE id=%s
            """,
            (state, alert_id)
        )

        db.commit()

        print(f"事件 {alert_id} 更新成功，新状态={state}")

        return jsonify({
            "success": True
        })

    except Exception as e:

        print("update_alert_state错误：", e)

        return jsonify({
            "success": False,
            "message": str(e)
        })

    finally:
        cursor.close()
        db.close()

# =========================
# 启动
# =========================
print(app.url_map)
if __name__ == '__main__':

    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=False
    )

@app.route('/update_note', methods=['POST'])
def update_note():
    data = request.json
    event_id = data.get('id')
    note = data.get('note', '').strip()

    if not event_id:
        return jsonify({'success': False, 'message': '缺少事件ID'})

    if len(note) < 15:
        return jsonify({'success': False, 'message': '备注不能少于15个字'})

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute('UPDATE events SET note=%s WHERE id=%s', (note, event_id))
        db.commit()
        return jsonify({'success': True, 'message': '保存成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        cursor.close()
        db.close()
