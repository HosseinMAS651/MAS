"""سرویس تولید گزارش رسمی و شکیل PDF برای رویداد و اتاق‌های پلتفرم ماس."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..core.timeutil import format_datetime_persian
from ..db.models import Room, SpeechFile

# ثبت قلم وزیرمتن
FONT_DIR = Path(__file__).resolve().parent.parent / "resources" / "fonts"
VAZIR_PATH = FONT_DIR / "Vazirmatn.ttf"
FONT_NAME = "Vazirmatn"

_font_registered = False


def _ensure_font_registered() -> str:
    global _font_registered
    if _font_registered:
        return FONT_NAME
    if VAZIR_PATH.exists():
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(VAZIR_PATH)))
            _font_registered = True
            return FONT_NAME
        except Exception:
            pass
    # Fallback to system font if necessary
    dejavu = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if dejavu.exists():
        try:
            pdfmetrics.registerFont(TTFont("DejaVu", str(dejavu)))
            _font_registered = True
            return "DejaVu"
        except Exception:
            pass
    return "Helvetica"


def fa(text: Any) -> str:
    """آماده‌سازی متن فارسی برای رندرینگ در ReportLab (RTL + اتصال حروف)."""
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""
    try:
        reshaped = arabic_reshaper.reshape(s)
        return get_display(reshaped)
    except Exception:
        return s


def format_ms_to_min_sec(ms: int) -> str:
    total_seconds = max(0, ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


class PdfReportService:
    @classmethod
    def generate_room_report(
        cls,
        room: Room,
        audit_events: list[dict[str, Any]],
        reaction_counts: dict[str, int],
    ) -> bytes:
        font_name = _ensure_font_registered()
        buffer = io.BytesIO()

        # تنظیمات صفحه A4 با مارجین‌های استاندارد
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        styles = getSampleStyleSheet()
        normal_style = styles["Normal"]

        # تم رنگی برند ماس (MAS Navy, Blue, Amber, Slate)
        c_primary = HexColor("#2563EB")     # Blue 600
        c_navy = HexColor("#0F172A")        # Slate 900
        c_light_bg = HexColor("#F8FAFC")    # Slate 50
        c_border = HexColor("#E2E8F0")      # Slate 200
        c_gray_text = HexColor("#64748B")   # Slate 500

        title_style = ParagraphStyle(
            "FaTitle",
            parent=normal_style,
            fontName=font_name,
            fontSize=18,
            leading=24,
            textColor=c_navy,
            alignment=1,  # Center
        )

        subtitle_style = ParagraphStyle(
            "FaSubTitle",
            parent=normal_style,
            fontName=font_name,
            fontSize=10,
            leading=14,
            textColor=c_gray_text,
            alignment=1,
        )

        section_heading = ParagraphStyle(
            "FaHeading",
            parent=normal_style,
            fontName=font_name,
            fontSize=12,
            leading=16,
            textColor=c_primary,
            alignment=2,  # Right
        )

        cell_style = ParagraphStyle(
            "FaCell",
            parent=normal_style,
            fontName=font_name,
            fontSize=9,
            leading=12,
            textColor=c_navy,
            alignment=1,  # Center
        )

        cell_header_style = ParagraphStyle(
            "FaCellHeader",
            parent=normal_style,
            fontName=font_name,
            fontSize=9,
            leading=12,
            textColor=HexColor("#FFFFFF"),
            alignment=1,
        )

        story = []

        # ۱. سربرگ گزارش
        story.append(Paragraph(fa("مــاس — سامانه مدیریت زمان و پخش سخنرانی"), subtitle_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph(fa(f"گزارش رسمی و جامع رویداد: {room.name}"), title_style))
        story.append(Spacer(1, 6))

        created_jalali = format_datetime_persian(room.created_at_ms)
        story.append(Paragraph(fa(f"تاریخ ایجاد اتاق: {created_jalali} | ظرفیت: {room.capacity} نفر"), subtitle_style))
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=1.5, color=c_primary, spaceBefore=4, spaceAfter=14))

        # ۲. مشخصات و خلاصه وضعیت اتاق
        speakers = sorted(room.speakers, key=lambda s: s.order_index)
        total_speakers = len(speakers)
        named_speakers = sum(1 for s in speakers if s.name.strip())
        finished_speakers = sum(1 for s in speakers if s.is_finished)

        timing_mode_fa = "زمان‌بندی همگانی" if room.timing_mode == "global" else "زمان‌بندی اختصاصی هر فرد"
        order_mode_fa = (
            "دستی" if room.order_mode == "manual"
            else "الفبایی" if room.order_mode == "alpha"
            else "بر اساس سن"
        )

        meta_data = [
            [
                Paragraph(fa(f"حالت زمان‌بندی: {timing_mode_fa}"), cell_style),
                Paragraph(fa(f"مالک اتاق: {room.owner.account_name or room.owner.username if room.owner else '—'}"), cell_style),
            ],
            [
                Paragraph(fa(f"ترتیب سخنرانی: {order_mode_fa}"), cell_style),
                Paragraph(fa(f"زمان پیش‌فرض: {room.global_seconds // 60} دقیقه ({room.global_seconds} ثانیه)"), cell_style),
            ],
            [
                Paragraph(fa(f"سخنرانان خاتمه‌یافته: {finished_speakers} از {named_speakers}"), cell_style),
                Paragraph(fa(f"کل اسلات‌ها: {total_speakers} (نام‌دار: {named_speakers})"), cell_style),
            ],
        ]
        meta_table = Table(meta_data, colWidths=[260, 260])
        meta_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), c_light_bg),
                ("BOX", (0, 0), (-1, -1), 1, c_border),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, c_border),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(meta_table)
        story.append(Spacer(1, 16))

        # ۳. جدول عملکرد سخنرانان و زمان‌ها
        story.append(Paragraph(fa("جدول عملکرد زمانی سخنرانان"), section_heading))
        story.append(Spacer(1, 6))

        headers = [
            Paragraph(fa("وضعیت"), cell_header_style),
            Paragraph(fa("اضافه وقت"), cell_header_style),
            Paragraph(fa("زمان مصرفی"), cell_header_style),
            Paragraph(fa("زمان مجاز"), cell_header_style),
            Paragraph(fa("جنسیت / سن"), cell_header_style),
            Paragraph(fa("نام سخنران"), cell_header_style),
            Paragraph(fa("ردیف"), cell_header_style),
        ]
        table_rows = [headers]

        for s in speakers:
            sp_name = s.name.strip() or "—"
            gender_fa = "مرد" if s.gender == "male" else "زن" if s.gender == "female" else "—"
            age_str = f"{s.age} سال" if s.age else "—"
            gender_age = f"{gender_fa} / {age_str}"

            limit_sec = s.speaking_seconds if room.timing_mode == "individual" else room.global_seconds
            limit_str = f"{limit_sec // 60:02d}:{limit_sec % 60:02d}"

            el_ms = s.timer.elapsed_ms if s.timer else 0
            ot_ms = s.timer.overtime_ms if s.timer else 0

            status_fa = "پایان‌یافته" if s.is_finished else "در انتظار / فعال"

            table_rows.append([
                Paragraph(fa(status_fa), cell_style),
                Paragraph(fa(f"+{format_ms_to_min_sec(ot_ms)}" if ot_ms > 0 else "—"), cell_style),
                Paragraph(fa(format_ms_to_min_sec(el_ms)), cell_style),
                Paragraph(fa(limit_str), cell_style),
                Paragraph(fa(gender_age), cell_style),
                Paragraph(fa(sp_name), cell_style),
                Paragraph(fa(str(s.order_index + 1)), cell_style),
            ])

        speaker_table = Table(table_rows, colWidths=[70, 75, 75, 70, 80, 125, 25])
        speaker_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), c_navy),
                ("BOX", (0, 0), (-1, -1), 1, c_border),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, c_border),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), c_light_bg]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(speaker_table)
        story.append(Spacer(1, 16))

        # ۴. خلاصهٔ واکنش‌های آنلاین تماشاگران
        reaction_sum = sum(reaction_counts.values())
        if reaction_sum > 0:
            story.append(Paragraph(fa("آمار واکنش‌های آنلاین تماشاگران"), section_heading))
            story.append(Spacer(1, 6))

            r_cols = [
                Paragraph(fa(f"قلب (❤️): {reaction_counts.get('heart', 0)}"), cell_style),
                Paragraph(fa(f"تشویق (👏): {reaction_counts.get('clap', 0)}"), cell_style),
                Paragraph(fa(f"پسندیدن (👍): {reaction_counts.get('like', 0)}"), cell_style),
                Paragraph(fa(f"آتش (🔥): {reaction_counts.get('fire', 0)}"), cell_style),
                Paragraph(fa(f"ستاره (⭐): {reaction_counts.get('star', 0)}"), cell_style),
            ]
            r_table = Table([r_cols], colWidths=[104, 104, 104, 104, 104])
            r_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), c_light_bg),
                    ("BOX", (0, 0), (-1, -1), 1, c_border),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, c_border),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ])
            )
            story.append(r_table)
            story.append(Spacer(1, 16))

        # ۵. فایل‌های پیوست و مستندات اتاق
        files = [f for f in room.files if f.upload_type in ["common", "speaker"]]
        if files:
            story.append(Paragraph(fa("فایل‌های پیوست و ارائه‌ها"), section_heading))
            story.append(Spacer(1, 6))

            f_rows = [
                [
                    Paragraph(fa("اندازه"), cell_header_style),
                    Paragraph(fa("مربوط به سخنران"), cell_header_style),
                    Paragraph(fa("نام فایل"), cell_header_style),
                    Paragraph(fa("نوع"), cell_header_style),
                ]
            ]
            for f in files:
                target_fa = f.speaker_name or "فایل مشترک کل اتاق" if f.upload_type == "common" else "سخنران اختصاصی"
                type_fa = "مشترک" if f.upload_type == "common" else "اختصاصی"
                size_kb = f"{f.size_bytes / 1024:.1f} KB"
                f_rows.append([
                    Paragraph(fa(size_kb), cell_style),
                    Paragraph(fa(target_fa), cell_style),
                    Paragraph(fa(f.filename), cell_style),
                    Paragraph(fa(type_fa), cell_style),
                ])

            f_table = Table(f_rows, colWidths=[80, 180, 200, 60])
            f_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#334155")),
                    ("BOX", (0, 0), (-1, -1), 1, c_border),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, c_border),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), c_light_bg]),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ])
            )
            story.append(f_table)
            story.append(Spacer(1, 16))

        # ۶. لاگ وقایع و تاریخچه فعالیت‌ها
        if audit_events:
            story.append(Paragraph(fa("تاریخچه وقایع و فعالیت‌های ثبت‌شده"), section_heading))
            story.append(Spacer(1, 6))

            evt_rows = [
                [
                    Paragraph(fa("توضیحات و جزئیات"), cell_header_style),
                    Paragraph(fa("نوع رویداد"), cell_header_style),
                    Paragraph(fa("زمان ثبت"), cell_header_style),
                ]
            ]
            for ev in audit_events[:25]:  # محدود به ۲۵ رویداد شاخص
                time_str = format_datetime_persian(ev.get("created_at_ms", 0))
                action_fa = ev.get("action", "")
                detail_fa = ev.get("detail", "")
                evt_rows.append([
                    Paragraph(fa(detail_fa), cell_style),
                    Paragraph(fa(action_fa), cell_style),
                    Paragraph(fa(time_str), cell_style),
                ])

            evt_table = Table(evt_rows, colWidths=[260, 130, 130])
            evt_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#475569")),
                    ("BOX", (0, 0), (-1, -1), 1, c_border),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, c_border),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), c_light_bg]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ])
            )
            story.append(evt_table)
            story.append(Spacer(1, 14))

        # پانویس گزارش
        story.append(HRFlowable(width="100%", thickness=0.5, color=c_border, spaceBefore=8, spaceAfter=8))
        story.append(Paragraph(fa("این سند به صورت خودکار توسط سامانه مدیریت زمان مـاس (MAS) تولید شده و معتبر است."), subtitle_style))

        doc.build(story)
        return buffer.getvalue()
