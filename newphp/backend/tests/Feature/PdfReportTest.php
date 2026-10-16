<?php

namespace Tests\Feature;

class PdfReportTest extends MasFeatureTestCase
{
    public function test_owner_report_is_pdf_even_with_html_in_room_name(): void
    {
        $auth = $this->registerUser();
        // رگرسیون B-02: متن کاربر باید escape شود و تولید PDF نباید ۵۰۰ بدهد.
        $room = $this->createRoom($auth, ['name' => 'جلسه <script>alert(1)</script>']);

        $response = $this->authed($auth)->get("/api/rooms/{$room['id']}/report/pdf");
        $response->assertOk();
        $this->assertSame('application/pdf', $response->headers->get('Content-Type'));
        $this->assertStringStartsWith('%PDF', $response->getContent());
    }

    public function test_public_report_is_pdf_without_audit_events(): void
    {
        $auth = $this->registerUser();
        $room = $this->createRoom($auth);

        $response = $this->anonymous()->get("/api/public/{$room['public_token']}/report/pdf");
        $response->assertOk();
        $this->assertStringStartsWith('%PDF', $response->getContent());
    }
}
