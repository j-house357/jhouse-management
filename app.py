import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import requests
import os
import io
import urllib.request
from supabase import create_client, Client

# ReportLab Imports
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- 1. ตั้งค่าการเชื่อมต่อ Supabase & Streamlit ---
st.set_page_config(
    page_title="J-House Has Love Management System",
    page_icon="🏨",
    layout="wide",
    initial_sidebar_state="expanded"
)

SUPABASE_URL = "https://qbpahjcijsvvrupfwnsq.supabase.co"
SUPABASE_KEY = "sb_publishable_IRm4poYIV8F0diD3_0nTvA_yChb9Ia0"

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# --- 2. ฟังก์ชันจัดการข้อมูลกับ Supabase ---
def get_rooms():
    response = supabase.table("rooms").select("*").execute()
    return response.data

def get_bookings():
    response = supabase.table("bookings").select("*").order("check_in", desc=True).execute()
    return response.data

def get_setting(key, default=""):
    try:
        response = supabase.table("settings").select("value").eq("key", key).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['value']
    except:
        pass
    return default

def set_setting(key, value):
    supabase.table("settings").upsert({"key": key, "value": value}).execute()

def send_line_notify(message):
    token = get_setting("line_token", "")
    if not token:
        return False
    url = 'https://notify-api.line.me/api/notify'
    headers = {'content-type': 'application/x-www-form-urlencoded', 'Authorization': 'Bearer ' + token}
    r = requests.post(url, headers=headers, data={'message': message})
    return r.status_code == 200

def check_room_availability(room_id, check_in, check_out, exclude_id=None):
    response = supabase.table("bookings").select("*").eq("room_id", room_id).neq("booking_status", "ยกเลิก").execute()
    bookings = response.data
    
    cin = pd.to_datetime(check_in).date()
    cout = pd.to_datetime(check_out).date()
    
    for b in bookings:
        if exclude_id and b.get('booking_id') == exclude_id:
            continue
        b_cin = pd.to_datetime(b['check_in']).date()
        b_cout = pd.to_datetime(b['check_out']).date()
        
        if not (cout <= b_cin or cin >= b_cout):
            return False
    return True

# --- 3. ฟังก์ชันสร้างใบเสร็จ PDF ภาษาไทย ---
def generate_pdf_receipt(booking_id, guest_name, guest_phone, room_id, check_in, check_out, num_guests, total_price):
    font_path = "THSarabunNew.ttf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/thsarabunnew/THSarabunNew.ttf"
            urllib.request.urlretrieve(url, font_path)
        except:
            pass
            
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('THSarabunNew', font_path))
        font_name = 'THSarabunNew'
    else:
        font_name = 'Helvetica'

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Normal'], fontName=font_name, fontSize=22, leading=26, alignment=1, textColor=colors.HexColor("#1E3A8A"))
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontName=font_name, fontSize=14, leading=18)
    bold_style = ParagraphStyle('BoldStyle', parent=styles['Normal'], fontName=font_name, fontSize=14, leading=18, textColor=colors.HexColor("#1E3A8A"))
    
    elements = []
    elements.append(Paragraph("<b>ใบเสร็จรับเงิน / Receipt</b>", title_style))
    elements.append(Paragraph("<b>เจเฮาส์มีความรัก (J-House Has Love)</b>", title_style))
    elements.append(Spacer(1, 15))
    
    data = [
        [Paragraph(f"<b>เลขที่ใบเสร็จ:</b> #{booking_id}", normal_style), Paragraph(f"<b>วันที่ออกใบเสร็จ:</b> {datetime.now().strftime('%d/%m/%Y')}", normal_style)],
        [Paragraph(f"<b>ชื่อผู้เข้าพัก:</b> {guest_name}", normal_style), Paragraph(f"<b>เบอร์โทรศัพท์:</b> {guest_phone}", normal_style)],
        [Paragraph(f"<b>ห้องพัก:</b> {room_id}", normal_style), Paragraph(f"<b>จำนวนผู้เข้าพัก:</b> {num_guests} ท่าน", normal_style)],
        [Paragraph(f"<b>วันเช็กอิน:</b> {check_in}", normal_style), Paragraph(f"<b>วันเช็กเอาต์:</b> {check_out}", normal_style)],
    ]
    t1 = Table(data, colWidths=[270, 270])
    t1.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
    elements.append(t1)
    elements.append(Spacer(1, 15))
    
    table_data = [
        [Paragraph("<b>รายการ</b>", bold_style), Paragraph("<b>จำนวนเงิน (บาท)</b>", bold_style)],
        [Paragraph(f"ค่าห้องพัก {room_id} ({check_in} ถึง {check_out})", normal_style), Paragraph(f"{total_price:,.2f}", normal_style)],
        [Paragraph("<b>ยอดชำระสุทธิ</b>", bold_style), Paragraph(f"<b>{total_price:,.2f}</b>", bold_style)]
    ]
    t2 = Table(table_data, colWidths=[380, 160])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F3F4F6")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#D1D5DB")),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("ขอบคุณที่ใช้บริการ เจเฮาส์มีความรัก ขอให้ท่านเดินทางโดยสวัสดิภาพ", ParagraphStyle('End', parent=normal_style, alignment=1)))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- 4. เมนูหลัก Streamlit ---
st.title("🏨 ระบบจัดการโรงแรม - เจเฮาส์มีความรัก")

menu = st.sidebar.radio(
    "📌 เมนูหลัก",
    ["📊 ทำรายการจอง", "📅 ปฏิทิน / สถานะการจอง", "⚙️ ตั้งค่าห้องพักและระบบ", "📤 ส่งออกข้อมูล"]
)

if menu == "📊 ทำรายการจอง":
    st.header("📊 ทำรายการจองห้องพัก")
    rooms = get_rooms()
    
    if not rooms:
        st.warning("⚠️ ยังไม่มีรายการห้องพัก กรุณาไปเพิ่มห้องพักในเมนู '⚙️ ตั้งค่าห้องพักและระบบ' ก่อนครับ")
    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("📝 ข้อมูลการจอง")
            guest_name = st.text_input("ชื่อ-นามสกุล ผู้เข้าพัก *")
            guest_phone = st.text_input("เบอร์โทรศัพท์")
            
            room_dict = {f"ห้อง {r['room_id']} ({r['room_type']}) - เริ่มต้น {r['base_price']:,.0f}B": r for r in rooms}
            selected_label = st.selectbox("เลือกห้องพัก", list(room_dict.keys()))
            selected_room = room_dict[selected_label]
            
            cin_col, cout_col = st.columns(2)
            check_in = cin_col.date_input("วันเช็กอิน", date.today())
            check_out = cout_col.date_input("วันเช็กเอาต์", date.today() + timedelta(days=1))
            
            num_guests = st.number_input("จำนวนผู้เข้าพัก (คน)", min_value=1, value=int(selected_room.get('base_capacity', 2)))
            
        with col2:
            st.subheader("💰 คำนวณราคา")
            nights = (check_out - check_in).days
            if nights <= 0:
                nights = 1
                
            b_price = selected_room['base_price']
            b_cap = selected_room.get('base_capacity', 2)
            e_fee = selected_room.get('extra_person_fee', 200.0)
            
            extra_ppl = max(0, num_guests - b_cap)
            extra_total = extra_ppl * e_fee
            nightly_rate = b_price + extra_total
            calc_total = nightly_rate * nights
            
            st.info(f"""
            * **ราคาห้องพัก**: {b_price:,.2f} บาท/คืน (รองรับ {b_cap} ท่านแรก)
            * **คนเกิน**: {extra_ppl} ท่าน (+{extra_total:,.2f} บาท/คืน)
            * **จำนวน**: {nights} คืน
            * **ราคารวมคำนวณ**: **{calc_total:,.2f} บาท**
            """)
            
            final_price = st.number_input("ราคาขายจริง/สุทธิ (บาท)", min_value=0.0, value=float(calc_total), step=100.0)
            
            if st.button("✅ ยืนยันการจอง & ออกใบเสร็จ", type="primary", use_container_width=True):
                if not guest_name:
                    st.error("กรุณากรอกชื่อผู้เข้าพัก")
                elif not check_room_availability(selected_room['room_id'], str(check_in), str(check_out)):
                    st.error(f"❌ ห้อง {selected_room['room_id']} ไม่ว่างในช่วงวันที่เลือก")
                else:
                    insert_data = {
                        "guest_name": guest_name,
                        "guest_phone": guest_phone,
                        "room_id": selected_room['room_id'],
                        "check_in": str(check_in),
                        "check_out": str(check_out),
                        "num_guests": int(num_guests),
                        "total_price": float(final_price),
                        "booking_status": "ยืนยันแล้ว"
                    }
                    res = supabase.table("bookings").insert(insert_data).execute()
                    
                    if res.data:
                        bid = res.data[0].get('booking_id', 'N/A')
                        st.success(f"🎉 บันทึกการจองสำเร็จ! (หมายเลขการจอง #{bid})")
                        
                        msg = f"\n🎉 มีรายการจองใหม่ #{bid}\nคุณ: {guest_name}\nห้อง: {selected_room['room_id']}\nเข้าพัก: {check_in} ถึง {check_out}\nจำนวน: {num_guests} ท่าน\nราคารวม: {final_price:,.2f} บาท"
                        send_line_notify(msg)
                        
                        pdf_data = generate_pdf_receipt(bid, guest_name, guest_phone, selected_room['room_id'], str(check_in), str(check_out), num_guests, final_price)
                        st.download_button(
                            label="📄 ดาวน์โหลดใบเสร็จรับเงิน (PDF)",
                            data=pdf_data,
                            file_name=f"Receipt_{bid}_{guest_name}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )

elif menu == "📅 ปฏิทิน / สถานะการจอง":
    st.header("📅 ตารางรายการจองและจัดการสถานะ")
    bookings_data = get_bookings()
    if not bookings_data:
        st.info("ยังไม่มีข้อมูลการจองในระบบ")
    else:
        df = pd.DataFrame(bookings_data)
        st.dataframe(df, use_container_width=True)
        
        st.subheader("🛠️ อัปเดตสถานะการจอง")
        c1, c2, c3 = st.columns([1, 2, 1])
        sel_id = c1.selectbox("เลือก ID การจอง", df['booking_id'])
        new_status = c2.radio("เปลี่ยนสถานะเป็น", ["เช็กอินแล้ว", "เช็กเอาต์แล้ว", "ยกเลิก"], horizontal=True)
        
        if c3.button("อัปเดตสถานะ"):
            supabase.table("bookings").update({"booking_status": new_status}).eq("booking_id", sel_id).execute()
            st.success(f"อัปเดตการจอง #{sel_id} เป็น '{new_status}' เรียบร้อยแล้ว")
            st.rerun()

elif menu == "⚙️️ ตั้งค่าห้องพักและระบบ":
    st.header("⚙️ ตั้งค่าห้องพักและระบบ")
    tab_room, tab_line = st.tabs(["🏠 จัดการห้องพักและราคา", "🔔 ตั้งค่า LINE Notify"])
    
    with tab_room:
        st.subheader("➕ เพิ่มห้องพักใหม่")
        with st.form("add_room"):
            a1, a2, a3 = st.columns(3)
            r_id = a1.text_input("หมายเลขห้องพัก (เช่น 101)")
            r_type = a2.selectbox("ประเภทห้อง", ["Standard Room", "Deluxe Room", "Suite", "Family Room"])
            r_price = a3.number_input("ราคาเริ่มต้น (บาท/คืน)", min_value=0.0, value=800.0, step=100.0)
            
            a4, a5 = st.columns(2)
            r_cap = a4.number_input("พักได้มาตรฐาน (คน)", min_value=1, value=2)
            r_extra = a5.number_input("ค่าบริการคนเกิน (บาท/คน/คืน)", min_value=0.0, value=200.0, step=50.0)
            
            if st.form_submit_button("บันทึกห้องพักใหม่"):
                if r_id:
                    try:
                        room_data = {
                            "room_id": r_id, "room_type": r_type, "base_price": r_price,
                            "base_capacity": r_cap, "extra_person_fee": r_extra, "status": "ว่าง"
                        }
                        supabase.table("rooms").insert(room_data).execute()
                        st.success(f"เพิ่มห้อง {r_id} เรียบร้อยแล้ว")
                        st.rerun()
                    except Exception as e:
                        st.error(f"เกิดข้อผิดพลาด: {e}")
                else:
                    st.error("กรุณาระบุเลขห้อง")

        st.divider()
        st.subheader("📋 รายการห้องพักทั้งหมด")
        rooms = get_rooms()
        for r in rooms:
            with st.expander(f"🏠 ห้อง {r['room_id']} - {r['room_type']}"):
                with st.form(f"edit_form_{r['room_id']}"):
                    e1, e2, e3 = st.columns(3)
                    utype = e1.selectbox("ประเภทห้อง", ["Standard Room", "Deluxe Room", "Suite", "Family Room"], index=0)
                    uprice = e2.number_input("ราคาฐาน", value=float(r['base_price']))
                    ustatus = e3.selectbox("สถานะ", ["ว่าง", "มีผู้เข้าพัก", "ปิดปรับปรุง"])
                    
                    if st.form_submit_button("💾 บันทึกการแก้ไข"):
                        supabase.table("rooms").update({"room_type": utype, "base_price": uprice, "status": ustatus}).eq("room_id", r['room_id']).execute()
                        st.success("อัปเดตสำเร็จ!")
                        st.rerun()

    with tab_line:
        st.subheader("🔔 ตั้งค่า LINE Notify Token")
        token = get_setting("line_token", "")
        new_token = st.text_input("LINE Notify Token", value=token, type="password")
        if st.button("บันทึก Token"):
            set_setting("line_token", new_token)
            st.success("บันทึกเรียบร้อย!")

elif menu == "📤 ส่งออกข้อมูล":
    st.header("📤 ส่งออกข้อมูลและการสรุปยอดขาย")
    bookings_data = get_bookings()
    if bookings_data:
        df_exp = pd.DataFrame(bookings_data)
        st.dataframe(df_exp, use_container_width=True)
        csv_data = df_exp.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดข้อมูลทั้งหมด (CSV)", data=csv_data, file_name="bookings.csv", mime="text/csv", type="primary")
    else:
        st.info("ยังไม่มีข้อมูล")
