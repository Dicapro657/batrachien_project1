from flask import Flask, request, jsonify
import sqlite3
import os

app = Flask(__name__)

DB_FILE = "batrachien.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/stats', methods=['POST'])
def get_stats():
    data = request.get_json()
    user_id = data.get('userId')
    if not user_id:
        return jsonify({'error': 'Missing userId'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT p.batrapoints, p.token_balance, p.energy, p.max_energy, l.level
        FROM points p
        JOIN levels l ON p.user_id = l.user_id
        WHERE p.user_id = ?
    """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'batrapoints': row['batrapoints'],
        'token_balance': row['token_balance'],
        'energy': row['energy'],
        'max_energy': row['max_energy'],
        'level': row['level']
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)