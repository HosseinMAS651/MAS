<?php

namespace App\Services;

use App\Models\Room;
use App\Support\Mas;
use Mpdf\Config\ConfigVariables;
use Mpdf\Config\FontVariables;
use Mpdf\Mpdf;

/**
 * معادل pdf_report_service.py — گزارش رسمی PDF اتاق با mPDF.
 * mPDF برخلاف ReportLab شکل‌دهی عربی/فارسی و bidi را خودش انجام می‌دهد؛
 * همهٔ متن‌های کاربر پیش از ورود به HTML با htmlspecialchars ایمن می‌شوند
 * (درس B-02: متن خام کاربر هرگز نباید وارد موتور PDF شود).
 */
class PdfReportService
{
    private function e(?string $text): string
    {
        return htmlspecialchars((string) $text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }

    private function formatDateTime(int $ms): string
    {
        if ($ms <= 0) {
            return '—';
        }

        return gmdate('Y-m-d H:i', intdiv($ms, 1000)).' UTC';
    }

    /**
     * @param  list<array{action: string, detail: string, created_at_ms: int}>  $auditEvents
     * @param  array<string, int>  $reactionCounts
     */
    public function generateRoomReport(Room $room, array $auditEvents, array $reactionCounts, bool $includeFiles = true): string
    {
        $mpdf = $this->createMpdf();

        $speakers = $room->speakers()->with('timer')->get()->all();
        $totalSpeakers = count($speakers);
        $namedSpeakers = 0;
        $finishedSpeakers = 0;
        foreach ($speakers as $s) {
            if (trim($s->name) !== '') {
                $namedSpeakers++;
            }
            if ($s->is_finished) {
                $finishedSpeakers++;
            }
        }

        $timingFa = $room->timing_mode === 'global' ? 'زمان‌بندی همگانی' : 'زمان‌بندی اختصاصی هر فرد';
        $orderFa = match ($room->order_mode) {
            'manual' => 'دستی',
            'alpha' => 'الفبایی',
            default => 'بر اساس سن',
        };
        $owner = $room->owner()->first();
        $ownerName = $owner ? ($owner->account_name !== '' ? $owner->account_name : $owner->username) : '—';
        $created = $this->formatDateTime($room->created_at_ms);

        $html = '<html dir="rtl" lang="fa"><head><meta charset="utf-8"><style>'
            .'body{font-family:vazirmatn,dejavusans,sans-serif;color:#0F172A;font-size:10pt}'
            .'.sub{color:#64748B;text-align:center;font-size:9pt}'
            .'.title{text-align:center;font-size:17pt;color:#0F172A;margin:4px 0}'
            .'.heading{color:#2563EB;font-size:12pt;margin:14px 0 6px}'
            .'table{border-collapse:collapse;width:100%}'
            .'td,th{border:0.5pt solid #E2E8F0;padding:5px;text-align:center;font-size:9pt}'
            .'th{background:#0F172A;color:#fff}'
            .'.meta td{background:#F8FAFC}'
            .'.alt td{background:#F8FAFC}'
            .'hr{border:none;border-top:1.5pt solid #2563EB;margin:10px 0}'
            .'</style></head><body>';

        // ۱. سربرگ
        $html .= '<p class="sub">مــاس — سامانه مدیریت زمان و پخش سخنرانی</p>';
        $html .= '<p class="title">گزارش رسمی و جامع رویداد: '.$this->e($room->name).'</p>';
        $html .= '<p class="sub">تاریخ ایجاد اتاق: '.$this->e($created).' | ظرفیت: '.$room->capacity.' نفر</p><hr>';

        // ۲. خلاصهٔ وضعیت
        $globalMinutes = intdiv($room->global_seconds, 60);
        $html .= '<table class="meta">'
            .'<tr><td>حالت زمان‌بندی: '.$this->e($timingFa).'</td><td>مالک اتاق: '.$this->e($ownerName).'</td></tr>'
            .'<tr><td>ترتیب سخنرانی: '.$this->e($orderFa).'</td><td>زمان پیش‌فرض: '.$globalMinutes.' دقیقه ('.$room->global_seconds.' ثانیه)</td></tr>'
            .'<tr><td>سخنرانان خاتمه‌یافته: '.$finishedSpeakers.' از '.$namedSpeakers.'</td><td>کل اسلات‌ها: '.$totalSpeakers.' (نام‌دار: '.$namedSpeakers.')</td></tr>'
            .'</table>';

        // ۳. جدول عملکرد سخنرانان
        $html .= '<p class="heading">جدول عملکرد زمانی سخنرانان</p><table><tr>'
            .'<th>ردیف</th><th>نام سخنران</th><th>جنسیت / سن</th><th>زمان مجاز</th><th>زمان مصرفی</th><th>اضافه وقت</th><th>وضعیت</th></tr>';
        foreach ($speakers as $i => $s) {
            $genderFa = $s->gender === 'male' ? 'مرد' : ($s->gender === 'female' ? 'زن' : '—');
            $ageStr = $s->age ? $s->age.' سال' : '—';
            $limitSec = $room->timing_mode === 'individual' ? $s->speaking_seconds : $room->global_seconds;
            $limitStr = sprintf('%02d:%02d', intdiv($limitSec, 60), $limitSec % 60);
            $timer = $s->timer;
            $el = $timer?->elapsed_ms ?? 0;
            $ot = $timer?->overtime_ms ?? 0;
            $status = $s->is_finished ? 'پایان‌یافته' : 'در انتظار / فعال';
            $name = trim($s->name) !== '' ? $s->name : '—';
            $html .= '<tr'.($i % 2 ? ' class="alt"' : '').'>'
                .'<td>'.($s->order_index + 1).'</td>'
                .'<td>'.$this->e($name).'</td>'
                .'<td>'.$this->e($genderFa.' / '.$ageStr).'</td>'
                .'<td>'.$limitStr.'</td>'
                .'<td>'.Mas::formatMsToMinSec($el).'</td>'
                .'<td>'.($ot > 0 ? '+'.Mas::formatMsToMinSec($ot) : '—').'</td>'
                .'<td>'.$this->e($status).'</td></tr>';
        }
        $html .= '</table>';

        // ۴. آمار واکنش‌ها
        if ($reactionCounts !== []) {
            $labels = ['heart' => 'قلب (❤️)', 'clap' => 'تشویق (👏)', 'like' => 'پسندیدن (👍)', 'fire' => 'آتش (🔥)', 'star' => 'ستاره (⭐)'];
            $html .= '<p class="heading">آمار واکنش‌های آنلاین تماشاگران</p><table><tr>';
            foreach ($labels as $key => $label) {
                $html .= '<td>'.$this->e($label).': '.(int) ($reactionCounts[$key] ?? 0).'</td>';
            }
            $html .= '</tr></table>';
        }

        // ۵. فایل‌های پیوست
        $files = [];
        if ($includeFiles) {
            foreach ($room->files()->get() as $f) {
                if (in_array($f->upload_type, ['common', 'speaker'], true) && $f->approval_status === 'approved') {
                    $files[] = $f;
                }
            }
        }
        if ($files !== []) {
            $html .= '<p class="heading">فایل‌های پیوست و ارائه‌ها</p><table><tr>'
                .'<th>نوع</th><th>نام فایل</th><th>مربوط به سخنران</th><th>اندازه</th></tr>';
            foreach ($files as $f) {
                $typeFa = $f->upload_type === 'common' ? 'مشترک' : 'اختصاصی';
                $targetFa = $f->upload_type === 'common' ? 'فایل مشترک کل اتاق' : ($f->speaker_name !== '' ? $f->speaker_name : 'سخنران اختصاصی');
                $sizeKb = number_format($f->size_bytes / 1024, 1).' KB';
                $html .= '<tr><td>'.$typeFa.'</td><td>'.$this->e($f->filename).'</td><td>'
                    .$this->e($targetFa).'</td><td>'.$sizeKb.'</td></tr>';
            }
            $html .= '</table>';
        }

        // ۶. تاریخچهٔ وقایع (حداکثر ۲۵ رویداد)
        if ($auditEvents !== []) {
            $html .= '<p class="heading">تاریخچه وقایع و فعالیت‌های ثبت‌شده</p><table><tr>'
                .'<th>زمان ثبت</th><th>نوع رویداد</th><th>توضیحات و جزئیات</th></tr>';
            foreach (array_slice($auditEvents, 0, 25) as $event) {
                $html .= '<tr><td>'.$this->e($this->formatDateTime((int) ($event['created_at_ms'] ?? 0))).'</td>'
                    .'<td>'.$this->e((string) ($event['action'] ?? '')).'</td>'
                    .'<td>'.$this->e((string) ($event['detail'] ?? '')).'</td></tr>';
            }
            $html .= '</table>';
        }

        $html .= '<hr><p class="sub">این سند به صورت خودکار توسط سامانه مدیریت زمان مـاس (MAS) تولید شده و معتبر است.</p>';
        $html .= '</body></html>';

        $mpdf->WriteHTML($html);

        return $mpdf->Output('', 'S');
    }

    private function createMpdf(): Mpdf
    {
        $defaultConfig = (new ConfigVariables)->getDefaults();
        $fontDirs = $defaultConfig['fontDir'];
        $defaultFontConfig = (new FontVariables)->getDefaults();
        $fontData = $defaultFontConfig['fontdata'];

        $customFontDir = storage_path('fonts');
        if (is_dir($customFontDir) && file_exists($customFontDir.'/Vazirmatn.ttf')) {
            $fontDirs[] = $customFontDir;
            $fontData['vazirmatn'] = ['R' => 'Vazirmatn.ttf'];
        }

        return new Mpdf([
            'mode' => 'utf-8',
            'format' => 'A4',
            'margin_left' => 13,
            'margin_right' => 13,
            'margin_top' => 13,
            'margin_bottom' => 13,
            'fontDir' => $fontDirs,
            'fontdata' => $fontData,
            'default_font' => isset($fontData['vazirmatn']) ? 'vazirmatn' : 'dejavusans',
            'autoScriptToLang' => true,
            'autoLangToFont' => true,
        ]);
    }
}
