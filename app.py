import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import requests
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io

# ---------------------------------------------------------
# 1. DATABASE SETUP & MIGRATION
# ---------------------------------------------------------
DB_FILE = 'jhouse_management.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # ตารางห้องพัก (Rooms)
    c.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            room_id TEXT PRIMARY KEY,
            room_type TEXT NOT NULL,
            base_price REAL NOT NULL,
            base_capacity INTEGER DEFAULT 2,
            extra_person_fee REAL DEFAULT 200.0,
            status TEXT DEFAULT 'ว่าง'
        )
    ''')
    
    # ตารางการจอง (Bookings)
    c.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_name TEXT NOT NULL,
            guest_phone TEXT,
            room_id TEXT NOT NULL,
            check_in DATE NOT NULL,
            check_out DATE NOT NULL,
            num_guests INTEGER DEFAULT 1,
            total_price REAL NOT NULL,
            booking_status TEXT DEFAULT 'ยืนยันแล้ว',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES rooms (room_id)
        )
    ''')
    
    # ตารางตั้งค่าระบบ (Settings)
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Migration: ตรวจสอบและเพิ่มคอลัมน์ใหม่หากเป็น DB เดิม
    c.execute("PRAGMA table_info(rooms)")
    columns = [col[1] for col in c.fetchall()]
    if 'base_capacity' not in columns:
        c.execute("ALTER TABLE rooms ADD COLUMN base_capacity INTEGER DEFAULT 2")
    if 'extra_person_fee' not in columns:
        c.execute("ALTER TABLE rooms ADD COLUMN extra_person_fee REAL DEFAULT 200.0")
        
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# 2. HELPER FUNCTIONS
# ---------------------------------------------------------
def get_setting(key, default=""):
    conn = get_db_connection()
    res = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return res['value'] if res else default

def set_setting(key, value):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def send_line_notify(message):
    token = get_setting("line_token", "")
    if not token:
        return False
    url = 'https://notify-api.line.me/api/notify'
    headers = {'content-type': 'application/x-www-form-urlencoded', 'Authorization': 'Bearer ' + token}
    r = requests.post(url, headers=headers, data={'message': message})
    return r.status_code == 200

def check_room_availability(room_id, check_in, check_out, exclude_booking_id=None):
    conn = get_db_connection()
    query = '''
        SELECT COUNT(*) as count FROM bookings 
        WHERE room_id = ? 
        AND booking_status != 'ยกเลิก'
        AND NOT (check_out <= ? OR check_in >= ?)
    '''
    params = [room_id, check_in, check_out]
    if exclude_booking_id:
        query += " AND booking_id != ?"
        params.append(exclude_booking_id)
        
    res = conn.execute(query, params).fetchone()
    conn.close()
    return res['count'] == 0

def generate_pdf_receipt(booking_info):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    p.setFont("Helvetica-Bold", 18)
    p.drawString(100, height - 80, "J-HOUSE HAS LOVE - RECEIPT")
    p.setFont("Helvetica", 10)
    p.drawString(100, height - 100, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    p.line(100, height - 110, width - 100, height - 110)
    
    y = height - 140
    details = [
        f"Booking ID: #{booking_info['booking_id']}",
        f"Guest Name: {booking_info['guest_name']}",
        f"Phone: {booking_info['guest_phone']}",
        f"Room ID: {booking_info['room_id']}",
        f"Check-In: {booking_info['check_in']}",
        f"Check-Out: {booking_info['check_out']}",
        f"Guests: {booking_info['num_guests']} Person(s)",
        f"Total Amount: {booking_info['total_price']:,.2f} THB"
    ]
    
    for line in details:
        p.drawString(100, y, line)
        y -= 25
        
    p.line(100, y - 10, width - 100, y - 10)
    p.drawString(100, y - 30, "Thank you for staying with us!")
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

# ---------------------------------------------------------
# 3. STREAMLIT UI LAYOUT
# ---------------------------------------------------------
st.set_page_config(page_title="เจเฮาส์มีความรัก - ระบบจัดการโรงแรม", layout="wide", page_icon="🏨")

st.sidebar.title("🏨 เจเฮาส์มีความรัก")
st.sidebar.caption("ระบบบริหารจัดการโรงแรมอัจฉริยะ")

menu = st.sidebar.radio(
    "เลือกเมนูการใช้งาน",
    ["📊 ทำรายการจอง", "📅 ปฏิทิน/สถานะห้องพัก", "⚙️ ตั้งค่าห้องพักและระบบ"]
)

# ---------------------------------------------------------
# MENU 1: MAKE A BOOKING
# ---------------------------------------------------------
if menu == "📊 ทำรายการจอง":
    st.header("📊 ทำรายการจองห้องพัก")
    
    conn = get_db_connection()
    rooms = conn.execute("SELECT * FROM rooms").fetchall()
    conn.close()
    
    if not rooms:
        st.warning("⚠️ ยังไม่มีรายการห้องพักในระบบ กรุณาไปเพิ่มห้องพักที่เมนู '⚙️ ตั้งค่าห้องพักและระบบ' ก่อนครับ")
    else:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("📝 กรอกข้อมูลการจอง")
            guest_name = st.text_input("ชื่อ-นามสกุล ผู้เข้าพัก *")
            guest_phone = st.text_input("เบอร์โทรศัพท์ติดต่อ")
            
            room_options = {f"ห้อง {r['room_id']} ({r['room_type']})": r for r in rooms}
            selected_room_label = st.selectbox("เลือกห้องพัก", list(room_options.keys()))
            selected_room = room_options[selected_room_label]
            
            c_in, c_out = st.columns(2)
            check_in = c_in.date_input("วันเช็กอิน", date.today())
            check_out = c_out.date_input("วันเช็กเอาต์", date.today() + pd.Timedelta(days=1))
            
            num_guests = st.number_input("จำนวนผู้เข้าพัก (คน)", min_value=1, value=selected_room['base_capacity'])
            
        with col2:
            st.subheader("💰 การคำนวณราคา")
            
            # คำนวณจำนวนคืน
            num_nights = (check_out - check_in).days
            if num_nights <= 0:
                st.error("❌ วันเช็กเอาต์ต้องอยู่หลังวันเช็กอินอย่างน้อย 1 คืน")
                num_nights = 1
                
            base_price = selected_room['base_price']
            base_cap = selected_room['base_capacity']
            extra_fee = selected_room['extra_person_fee']
            
            # คำนวณคนเกิน
            extra_guests = max(0, num_guests - base_cap)
            extra_charge = extra_guests * extra_fee
            
            calculated_price_per_night = base_price + extra_charge
            suggested_total = calculated_price_per_night * num_nights
            
            st.info(f"""
            * **ราคาห้องพักพื้นฐาน**: {base_price:,.2f} บาท/คืน (สำหรับ {base_cap} คนแรก)
            * **ค่าผู้เข้าพักเสริม**: {extra_charge:,.2f} บาท/คืน ({extra_guests} คน × {extra_fee:,.2f} บาท)
            * **ระยะเวลาพัก**: {num_nights} คืน
            * **ราคารวมคำนวณอัตโนมัติ**: **{suggested_total:,.2f} บาท**
            """)
            
            # ช่องปรับเปลี่ยนราคาไฟนอลได้ตามต้องการ
            final_price = st.number_input("ราคาปรับเปลี่ยนสุทธิ (บาท)", min_value=0.0, value=float(suggested_total), step=100.0)
            
            if st.button("✅ บันทึกการจองและออกใบเสร็จ", type="primary"):
                if not guest_name:
                    st.error("กรุณากรอกชื่อผู้เข้าพัก")
                elif not check_room_availability(selected_room['room_id'], check_in, check_out):
                    st.error(f"❌ ห้อง {selected_room['room_id']} ถูกจองแล้วในช่วงวันที่ {check_in} ถึง {check_out}")
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO bookings (guest_name, guest_phone, room_id, check_in, check_out, num_guests, total_price)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (guest_name, guest_phone, selected_room['room_id'], check_in, check_out, num_guests, final_price))
                    booking_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    
                    st.success(f"🎉 บันทึกการจองสำเร็จ! หมายเลขการจอง #{booking_id}")
                    
                    # ส่ง LINE Notify
                    msg = f"\n🎉 มีการจองใหม่ (#{booking_id})\nคุณ {guest_name}\nห้อง: {selected_room['room_id']}\nเช็กอิน: {check_in}\nเช็กเอาต์: {check_out}\nจำนวน: {num_guests} ท่าน\nยอดรวม: {final_price:,.2f} บาท"
                    send_line_notify(msg)
                    
                    # สร้าง PDF
                    booking_data = {
                        'booking_id': booking_id,
                        'guest_name': guest_name,
                        'guest_phone': guest_phone,
                        'room_id': selected_room['room_id'],
                        'check_in': check_in,
                        'check_out': check_out,
                        'num_guests': num_guests,
                        'total_price': final_price
                    }
                    pdf_file = generate_pdf_receipt(booking_data)
                    st.download_button(
                        label="📄 ดาวน์โหลดใบเสร็จรับเงิน (PDF)",
                        data=pdf_file,
                        file_name=f"receipt_booking_{booking_id}.pdf",
                        mime="application/pdf"
                    )

# ---------------------------------------------------------
# MENU 2: CALENDAR & ROOM STATUS
# ---------------------------------------------------------
elif menu == "📅 ปฏิทิน/สถานะห้องพัก":
    st.header("📅 รายการจองและสถานะห้องพัก")
    
    conn = get_db_connection()
    df_bookings = pd.read_sql_query('''
        SELECT b.booking_id, b.guest_name, b.guest_phone, b.room_id, b.check_in, b.check_out, b.num_guests, b.total_price, b.booking_status 
        FROM bookings b ORDER BY b.check_in DESC
    ''', conn)
    conn.close()
    
    if df_bookings.empty:
        st.info("ยังไม่มีข้อมูลการจองในระบบ")
    else:
        st.dataframe(df_bookings, use_container_width=True)
        
        st.subheader("⚙️ จัดการการจอง")
        col_id, col_act = st.columns([1, 2])
        booking_to_mod = col_id.selectbox("เลือกหมายเลขการจอง", df_bookings['booking_id'])
        action = col_act.radio("การดำเนินการ", ["เปลี่ยนเป็น 'เช็กอินแล้ว'", "เปลี่ยนเป็น 'เช็กเอาต์แล้ว'", "ยกเลิกการจอง"], horizontal=True)
        
        if st.button("ยืนยันการเปลี่ยนแปลง"):
            conn = get_db_connection()
            status_map = {
                "เปลี่ยนเป็น 'เช็กอินแล้ว'": "เช็กอินแล้ว",
                "เปลี่ยนเป็น 'เช็กเอาต์แล้ว'": "เช็กเอาต์แล้ว",
                "ยกเลิกการจอง": "ยกเลิก"
            }
            conn.execute("UPDATE bookings SET booking_status = ? WHERE booking_id = ?", (status_map[action], booking_to_mod))
            conn.commit()
            conn.close()
            st.success("อัปเดตสถานะเรียบร้อยแล้ว!")
            st.rerun()

# ---------------------------------------------------------
# MENU 3: ROOM & SYSTEM SETTINGS (EDIT ROOM & PRICING)
# ---------------------------------------------------------
elif menu == "⚙️ ตั้งค่าห้องพักและระบบ":
    st.header("⚙️ ตั้งค่าห้องพักและระบบ")
    
    tab1, tab2 = st.tabs(["🏠 จัดการห้องพักและราคา", "🔔 ตั้งค่า LINE Notify"])
    
    with tab1:
        st.subheader("➕ เพิ่มรายการห้องพักใหม่")
        with st.form("add_room_form"):
            c1, c2, c3 = st.columns(3)
            new_room_id = c1.text_input("หมายเลขห้องพัก (เช่น 101)")
            new_room_type = c2.selectbox("ประเภทห้องพัก", ["Standard Room", "Deluxe Room", "Suite", "Family Room"])
            new_base_price = c3.number_input("ราคาฐานเริ่มต้น (บาท/คืน)", min_value=0.0, value=800.0, step=100.0)
            
            c4, c5 = st.columns(2)
            new_base_cap = c4.number_input("จำนวนคนพักมาตรฐาน (คน)", min_value=1, value=2)
            new_extra_fee = c5.number_input("ค่าบริการคนเกิน (บาท/คน/คืน)", min_value=0.0, value=200.0, step=50.0)
            
            submit_add = st.form_submit_button("บันทึกห้องพักใหม่")
            
            if submit_add:
                if not new_room_id:
                    st.error("กรุณาระบุหมายเลขห้องพัก")
                else:
                    conn = get_db_connection()
                    try:
                        conn.execute('''
                            INSERT INTO rooms (room_id, room_type, base_price, base_capacity, extra_person_fee)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (new_room_id, new_room_type, new_base_price, new_base_cap, new_extra_fee))
                        conn.commit()
                        st.success(f"เพิ่มห้องพัก {new_room_id} เรียบร้อยแล้ว!")
                    except sqlite3.IntegrityError:
                        st.error(f"หมายเลขห้อง {new_room_id} มีอยู่ในระบบแล้ว")
                    finally:
                        conn.close()
                        st.rerun()
                        
        st.divider()
        st.subheader("📋 รายการห้องพักทั้งหมด (แก้ไข/ปรับราคา)")
        
        conn = get_db_connection()
        rooms_list = conn.execute("SELECT * FROM rooms").fetchall()
        conn.close()
        
        for room in rooms_list:
            with st.expander(f"🏠 ห้อง {room['room_id']} - {room['room_type']} (ราคาเริ่มต้น: {room['base_price']:,.2f} บาท)"):
                with st.form(f"edit_room_{room['room_id']}"):
                    ec1, ec2, ec3 = st.columns(3)
                    e_type = ec1.selectbox("ประเภทห้อง", ["Standard Room", "Deluxe Room", "Suite", "Family Room"], 
                                           index=["Standard Room", "Deluxe Room", "Suite", "Family Room"].index(room['room_type']) if room['room_type'] in ["Standard Room", "Deluxe Room", "Suite", "Family Room"] else 0)
                    e_price = ec2.number_input("ราคาฐาน (บาท/คืน)", min_value=0.0, value=float(room['base_price']), step=100.0)
                    e_status = ec3.selectbox("สถานะห้อง", ["ว่าง", "มีผู้เข้าพัก", "ปิดปรับปรุง"], index=["ว่าง", "มีผู้เข้าพัก", "ปิดปรับปรุง"].index(room['status']) if room['status'] in ["ว่าง", "มีผู้เข้าพัก", "ปิดปรับปรุง"] else 0)
                    
                    ec4, ec5 = st.columns(2)
                    e_cap = ec4.number_input("คนพักมาตรฐาน", min_value=1, value=int(room['base_capacity']))
                    e_extra = ec5.number_input("ค่าบริการคนเกิน (บาท/คน)", min_value=0.0, value=float(room['extra_person_fee']), step=50.0)
                    
                    btn_save, btn_del = st.columns([1, 1])
                    saved = btn_save.form_submit_button("💾 บันทึกการแก้ไข")
                    deleted = btn_del.form_submit_button("🗑️ ลบห้องพักนี้", type="primary")
                    
                    if saved:
                        conn = get_db_connection()
                        conn.execute('''
                            UPDATE rooms SET room_type=?, base_price=?, base_capacity=?, extra_person_fee=?, status=?
                            WHERE room_id=?
                        ''', (e_type, e_price, e_cap, e_extra, e_status, room['room_id']))
                        conn.commit()
                        conn.close()
                        st.success(f"อัปเดตข้อมูลห้อง {room['room_id']} สำเร็จ!")
                        st.rerun()
                        
                    if deleted:
                        conn = get_db_connection()
                        conn.execute("DELETE FROM rooms WHERE room_id=?", (room['room_id'],))
                        conn.commit()
                        conn.close()
                        st.warning(f"ลบห้องพัก {room['room_id']} เรียบร้อยแล้ว")
                        st.rerun()

    with tab2:
        st.subheader("🔔 ตั้งค่า LINE Notify Token")
        current_token = get_setting("line_token", "")
        token_input = st.text_input("LINE Notify Token", value=current_token, type="password")
        
        if st.button("บันทึก Token"):
            set_setting("line_token", token_input)
            st.success("บันทึก Token เรียบร้อยแล้ว!")
            
        if st.button("🧪 ทดสอบส่งการแจ้งเตือน"):
            if send_line_notify("ทดสอบการแจ้งเตือนจากระบบ J-House Has Love"):
                st.success("ส่งข้อความทดสอบสำเร็จ!")
            else:
                st.error("ส่งข้อความไม่สำเร็จ กรุณาตรวจสอบ Token อีกครั้ง")
