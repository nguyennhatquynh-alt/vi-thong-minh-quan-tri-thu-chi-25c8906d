# Ví Thông Minh - Quản Trị Thu Chi & Ngân Sách Cá Nhân

Ứng dụng được tạo bởi Gemini Genesis Engine.

## Cài lên Render của bạn (1 chạm)
Bấm nút **Deploy to Render** trên trang xưởng, đăng nhập Render bằng email của bạn và xác nhận. Ứng dụng chạy trên tài khoản Render của bạn.

Render sẽ hỏi biến `ENROLL_CODE`: dán mã ghi danh lấy từ trang xưởng (Khâu 4). Biến `APP_KEY` do Render tự tạo, bạn không cần nhập.

## Tệp trong kho
- `public/`: giao diện, biểu tượng, chế độ offline
- `server.py`: máy chủ nhỏ phục vụ ứng dụng
- `render.yaml`: cấu hình triển khai (tắt tự động cập nhật)
