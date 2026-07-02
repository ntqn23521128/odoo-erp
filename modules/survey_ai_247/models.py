from odoo import models, fields, api
import requests
import json

# =====================================================================
# 1. BỘ NÃO TỰ ĐỘNG 1: LẮNG NGHE DỰ ÁN ĐỂ GỬI EMAIL
# =====================================================================
class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Ghi đè hàm write để tự động gửi email khi chuyển sang giai đoạn "Hoàn tất"
    def write(self, vals):
        res = super(ProjectProject, self).write(vals)
        if 'stage_id' in vals:
            for record in self:
                if record.stage_id.name == 'Hoàn tất' and record.partner_id:
                    # Truy vấn tìm khảo sát có tiêu đề chứa "247 Express"
                    survey = self.env['survey.survey'].sudo().search([('title', 'ilike', '247 Express')], limit=1)
                    # Nếu tìm thấy khảo sát, tạo một bản ghi user_input mới (Phiên làm bài(Answer Sheet) mới) dành riêng cho vị khách hàng này.
                    if survey:
                        user_input = self.env['survey.user_input'].sudo().create({
                            'survey_id': survey.id,
                            'partner_id': record.partner_id.id,
                            'email': record.partner_id.email,
                            'x_project_id': record.id,
                            'state': 'new',
                        })

                        # Sinh ra link khảo sát có đính kèm access_token để nhận diện khách hàng khi họ bấm vào làm khảo sát
                        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                        survey_url = f"{base_url}/survey/start/{survey.access_token}?answer_token={user_input.access_token}"
                        target_email = record.partner_id.email or 'nguyenthiquynhnhu26092005@gmail.com'

                        mail_values = {
                            'subject': f'Mời đánh giá chất lượng dịch vụ dự án {record.name}',
                            'email_from': 'CSKH 247 Express <nguyenthiquynhnhu26092005@gmail.com>',
                            'email_to': target_email,
                            'body_html': f"""
                                <p>Xin chào {record.partner_id.name},</p>
                                <p>Cảm ơn bạn đã sử dụng dịch vụ của 247 Express. Vui lòng dành 1 phút để đánh giá chất lượng dự án tại đường link dưới đây:</p>
                                <p><a href="{survey_url}" style="padding: 8px 12px; background-color: #875A7B; color: white; text-decoration: none; border-radius: 4px;"><b>Bắt đầu Khảo sát</b></a></p>
                            """
                        }

                        # Chui vao mail.mail để gửi email đi
                        self.env['mail.mail'].sudo().create(mail_values).send()
                        record.message_post(body=f"Module V2 đã gửi Email tự động. Link: <a href='{survey_url}' target='_blank'>Bấm vào đây</a>")
        return res

# =====================================================================
# 2. BỘ NÃO TỰ ĐỘNG 2: LẮNG NGHE KHẢO SÁT & CẢNH BÁO CHURN
# =====================================================================
class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    # Tạo thêm các cột mới trong bảng survey_user_input để lưu kết quả phân tích AI
    x_project_id = fields.Many2one('project.project', string='Dự án liên quan')
    x_ai_sentiment = fields.Selection([
        ('positive', 'Tích cực'),
        ('negative', 'Tiêu cực'),
        ('neutral', 'Trung lập')
    ], string='Sắc thái (AI)')
    
    x_ai_summary = fields.Char(string='Tóm tắt phản hồi (AI)')
    x_ai_suggested_action = fields.Char(string='Đề xuất xử lý (AI)')
    x_ai_root_cause = fields.Char(string='Nguyên nhân cốt lõi (AI)')
    x_ai_draft_reply = fields.Text(string='Email phản hồi (AI)')
    x_ai_churn_intent = fields.Selection([
        ('high', 'Cao (Dọa tẩy chay/rời đi)'),
        ('low', 'Thấp (Chỉ phàn nàn sự vụ)')
    ], string='Ý định rời bỏ (AI)')
    x_is_churn_risk = fields.Boolean(string='BẬT CẢNH BÁO RỜI BỎ', default=False)


    # Ghi đè hàm write để tự động gọi AI (ham action_analyze_ai()) khi trạng thái khảo sát chuyển sang 'done'
    def write(self, vals):
        res = super(SurveyUserInput, self).write(vals)
        if 'state' in vals and vals['state'] == 'done':
            for record in self:
                record.action_analyze_ai()
        return res

    def action_analyze_ai(self):
        for record in self:
            # Gom tất cả câu hỏi + câu trả lời vào 1 đoạn văn bản dài để gửi cho AI phân tích
            all_answers = []
            for line in record.user_input_line_ids:
                question = line.question_id.title
                val = (line.value_char_box or line.value_text_box or 
                       (str(line.value_numerical_box) if line.value_numerical_box else "") or
                       (line.suggested_answer_id.value if line.suggested_answer_id else ""))
                if val and val not in ["0.0", ""]:
                    all_answers.append(f"{question}: {val}")
            
            full_context = "\n".join(all_answers)
            if not full_context: continue

            # Chìa khóa vào nhà Google
            api_key = "AIzaSyB80m5pzipMCRPETIpbZYvnIXKMppaRNLA" 
            
            # Tối ưu Prompt để AI lấy thêm CHURN_INTENT
            prompt = f"""
            Bạn là Trưởng phòng CSKH của 247 Express. Dựa trên kết quả khảo sát:
            {full_context}
            Hãy phân tích và trả lời DUY NHẤT theo cấu trúc sau (không giải thích thêm):
            SENTIMENT: [Tích cực/Tiêu cực/Trung lập]
            SUMMARY: [Tóm tắt 1 câu cực ngắn]
            ACTION: [Thưởng/Phạt/Nhắc nhở/Kiểm tra gấp]
            ROOT_CAUSE: [BẮT BUỘC chỉ chọn đúng 1 từ khóa trong danh sách sau để phân loại: "Giao hàng chậm", "Thái độ nhân viên", "Hư hỏng/Mất hàng", "Chất lượng dịch vụ tốt", "Khác"]
            CHURN_INTENT: [Đánh giá CAO nếu khách dọa bỏ dùng dịch vụ/chuyển hãng khác. Đánh giá THẤP nếu khách chỉ phàn nàn nhẹ]
            DRAFT_EMAIL: [Soạn 1 email CSKH (khoảng 100 chữ) thay mặt 247 Express gửi khách. 
            - Nếu Tiêu cực: Phải xin lỗi chân thành, nhắc lại ĐÚNG nguyên nhân khách gặp phải để khách thấy mình được lắng nghe, cam kết Ban Giám đốc đang điều tra và sẽ xử lý nghiêm. 
            - Nếu Tích cực/Trung lập: Cảm ơn trân trọng. 
            - YÊU CẦU TRÌNH BÀY: Văn phong chuyên nghiệp, ngắt dòng rõ ràng bằng phím Enter giữa các đoạn. Xưng hô "Quý khách". Ký tên: "Ban Giám đốc 247 Express".]
            """

            # Chuẩn bị địa chỉ nhận (link API của Google Gemini) và đóng gói prompt lại thành một hộp bưu kiện chuẩn JSON (payload) để gửi đi
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            
            try:
                response = requests.post(url, json=payload, timeout=30)
                result = response.json()
                
                if 'candidates' in result:
                    ai_reply = result['candidates'][0]['content']['parts'][0]['text']
                    
                    sentiment_val = 'neutral'
                    if "Tích cực" in ai_reply: sentiment_val = 'positive'
                    elif "Tiêu cực" in ai_reply: sentiment_val = 'negative'
                    
                    summary_text = action_text = root_cause_text = draft_email_text = ""
                    churn_intent_val = 'low'
                    
                    if "DRAFT_EMAIL:" in ai_reply:
                        parts = ai_reply.split("DRAFT_EMAIL:")
                        draft_email_text = parts[1].strip()
                        ai_reply_header = parts[0] 
                    else:
                        ai_reply_header = ai_reply

                    for line in ai_reply_header.split('\n'):
                        if "SUMMARY:" in line: summary_text = line.replace("SUMMARY:", "").strip()
                        if "ACTION:" in line: action_text = line.replace("ACTION:", "").strip()
                        if "ROOT_CAUSE:" in line: root_cause_text = line.replace("ROOT_CAUSE:", "").strip()
                        if "CHURN_INTENT:" in line: 
                            if "CAO" in line.upper(): churn_intent_val = 'high'
                    
                    # Xác định đối tượng khách hàng để liên kết (ưu tiên lấy từ partner_id, nếu không có thì lấy từ dự án)
                    partner_record = record.partner_id or (record.x_project_id.partner_id if record.x_project_id else False)

                    # Logic cảnh báo Rời bỏ, Cờ báo động đỏ mặc định TẮT
                    churn_alert_flag = False
                    if sentiment_val == 'negative':
                        if churn_intent_val == 'high':
                            churn_alert_flag = True
                        elif partner_record:
                            # Truy vấn Odoo: Khách này đã từng chê lần nào chưa?
                            past_negative = self.env['survey.user_input'].sudo().search_count([
                                ('partner_id', '=', partner_record.id),
                                ('x_ai_sentiment', '=', 'negative'),
                                ('id', '!=', record.id) 
                            ])
                            if past_negative >= 1:
                                churn_alert_flag = True

                    # Cập nhật kết quả phân tích AI vào các cột mới trong bảng survey_user_input
                    record.write({
                        'partner_id': partner_record.id if partner_record else False,
                        'x_ai_sentiment': sentiment_val,
                        'x_ai_summary': summary_text[:255], 
                        'x_ai_suggested_action': action_text[:255],
                        'x_ai_root_cause': root_cause_text[:255],
                        'x_ai_churn_intent': churn_intent_val,
                        'x_is_churn_risk': churn_alert_flag,
                        'x_ai_draft_reply': draft_email_text
                    })

                    # Gửi Mail
                    if draft_email_text and partner_record and partner_record.email:
                        mail_values = {
                            'subject': f'Phản hồi từ 247 Express về dịch vụ của bạn',
                            'email_from': 'CSKH 247 Express <nguyenthiquynhnhu26092005@gmail.com>',
                            'email_to': partner_record.email,
                            'body_html': f'<p>{draft_email_text.replace(chr(10), "<br/>")}</p>'
                        }
                        self.env['mail.mail'].sudo().create(mail_values).send()
                        record.message_post(body="Đã TỰ ĐỘNG GỬI email thư phản hồi cho khách hàng.")
                    
                    # Báo động tức thời ve nguy co rời bỏ
                    if churn_alert_flag:
                        project_name = record.x_project_id.name if record.x_project_id else "Không rõ"
                        
                        # Truy vấn tìm nhân viên nội bộ (share = False tức là loại trừ khách hàng)
                        all_employees = self.env['res.users'].sudo().search([('share', '=', False)])
                        
                        # Vòng lặp phát thông báo cho từng người
                        for employee in all_employees:
                            # Tránh gửi thông báo cho OdooBot (ID = 1) để đỡ rác hệ thống
                            if employee.id != 1: 
                                record.activity_schedule(
                                    'mail.mail_activity_data_todo',
                                    summary=f'KHÁCH VIP SẮP RỜI BỎ! (Dự án: {project_name})',
                                    note=f"Khách hàng dọa tẩy chay hoặc phàn nàn nhiều lần. TẤT CẢ NHÂN VIÊN LƯU Ý!\n- Lỗi: {root_cause_text}\n- Tóm tắt: {summary_text}",
                                    user_id=employee.id 
                                )
                    elif sentiment_val == "negative" or "Kiểm tra gấp" in action_text:
                        project_name = record.x_project_id.name if record.x_project_id else "Không rõ"
                        record.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=f'Khách phàn nàn (Dự án: {project_name})',
                            note=f"Vấn đề: {summary_text}.",
                            user_id=record.survey_id.user_id.id 
                        )

                    # Ghi log kết quả phân tích AI vào phần thảo luận của khảo sát
                    record.message_post(body=f"AI Analysis: {ai_reply}")
                else:
                    # Lấy lý do chính xác từ Google để in ra màn hình
                    err_msg = result.get('error', {}).get('message', str(result))
                    record.message_post(body=f"AI từ chối trả lời. Chi tiết lỗi từ Google: {err_msg}")
            except Exception as e:
                record.message_post(body=f"Không kết nối được AI: {str(e)}")
