# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY, verdict judge lưu sẵn trong CSV). FAIL là lớp dương.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng** — chỉ cho tone, non-blocking, kèm audit định kỳ |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (exit 1) | **loại** — không được dùng làm gate |

Ma trận nhầm lẫn:
- tone_ok: tp 24 · fp 4 · fn 6 · tn 66. Tỉ lệ FAIL quan sát 0.28, sau Rogan-Gladen **0.30** (sens 0.8, spec 66/70 = 0.943).
- helpful: tp 9 · fp 0 · fn 21 · tn 70. Tỉ lệ FAIL quan sát 0.09, sau Rogan-Gladen **0.30**: judge chỉ thấy chưa tới 1/3 số reply thật sự không hữu ích.

## Audit thủ công 10 bất đồng (tone) + 6 mẫu (helpful)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã. Rubric: thêm "xưng hô: LogiX / anh/chị; cấm em–anh, bạn, nha/nhé". |
| 2 | H-017 "bạn ơi … rồi nha" | PASS | FAIL | Người | Cùng lỗi xưng hô, judge coi "thân thiện" là đạt. Thêm ví dụ FAIL vào few-shot. |
| 3 | H-029 "vui lòng chờ… không cần nhắn thêm" | PASS | FAIL | Người | Judge chỉ bắt từ khóa lịch sự. Rubric: "câu mệnh lệnh / chặn khách liên hệ = FAIL dù có 'Dạ, vui lòng'". |
| 4 | H-042 "đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu xin lỗi. Rubric: "xin lỗi không bắt buộc khi đã giải quyết xong; ngắn gọn ≠ cộc lốc". |
| 5 | H-051 "đã refund 90.000đ" | FAIL | PASS | Người | CS LogiX cho phép từ "refund". Rubric: thêm whitelist thuật ngữ (refund, ship, voucher). |
| 6 | H-063 "đã hoàn 20.000đ và sẽ hoàn thêm" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống. Đây không phải lỗi tone mà là lỗi nội dung (họ FM-08), nên chuyển sang grader code: reply chỉ được nêu số ledger và không được hứa thêm. |
| 7 | H-070 "… ạ 😂😂" | PASS | FAIL | Người | Rubric: "emoji cười trong khiếu nại = FAIL". |
| 8 | H-081 "đơn O-107 chưa đủ điều kiện…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket), như ghi chú trong CSV. Hành động: sửa nhãn người thành FAIL rồi chạy lại calibration; cần người thứ hai gán nhãn độc lập. |
| 9 | H-088 "Dạ, dạ, LogiX…" | FAIL | PASS | Hòa (lỗi nhỏ) | Lặp từ do gõ. Rubric: "lỗi gõ đơn lẻ không làm FAIL tone"; judge đang quá nghiêm. |
| 10 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Dịch máy, mất dấu. Rubric: "tiếng Việt không dấu = FAIL". Có thể chặn trước bằng code (tỉ lệ ký tự có dấu). |
| 11 | HL-015 "đã hoàn 55.000đ cho đơn O-112" (ledger 40.000đ) | PASS | FAIL | Người | Judge không thấy ledger nên **không thể** biết số sai. Đây là FM-08 và phải chấm bằng code (`reply_matches_ledger`). |
| 12 | HL-020 "đã hoàn 90.000đ" (ledger 120.000đ) | PASS | FAIL | Người | Như trên: 18/21 FN của helpful có ghi chú "ledger ghi …". |
| 13 | HL-016 / HL-028 / HL-035 (xin lỗi dài + số sai) | PASS | FAIL | Người | **Verbosity bias**: reply dài, nhiều câu xin lỗi được chấm "helpful" dù số tiền sai. Rubric: "độ dài và lời xin lỗi không cộng điểm". |
| 14 | HL-047 / HL-091 / HL-097 "Ok bạn, đơn … xử lý rồi nhé." | PASS | FAIL | Người | Không nêu kết quả, số tiền hay thời gian. Rubric: "helpful = nêu trạng thái + số tiền (nếu có) + bước tiếp theo". |

## Kết luận
- **tone_ok dùng được** (κ 0.757, P 0.857, R 0.800 ≥ FLOORS). 6/10 bất đồng là FN do rubric thiếu luật xưng hô, emoji và mệnh lệnh: sửa rubric và thêm few-shot. 1 bất đồng (H-081) do nhãn người sai: sửa nhãn. Tone vẫn **non-blocking**, vì R 0.8 nghĩa là cứ 5 reply sai tone thì lọt 1.
- **helpful bị loại**: κ 0.375 < 0.6 và R 0.300 < 0.7 (fn 21/30). P = 1.0 nhìn đẹp nhưng chỉ vì judge hiếm khi nói FAIL; precision cao kèm recall thấp là dấu hiệu một judge "dễ dãi". Lý do chính: 18/21 FN là reply nêu **sai số tiền**. Judge không đọc ledger nên không có thông tin để chấm, và bias độ dài khiến reply xin lỗi dài được cho qua. Dùng nó làm gate sẽ báo xanh trên đúng loại lỗi đắt nhất (FM-08). Tiêu chí "đúng số tiền" chuyển sang code (`reply_matches_ledger`). Phần "đủ ý" (trạng thái + bước tiếp theo) cần rubric mới và calibration lại trước khi dùng.
- Rogan-Gladen: tỉ lệ fail thực ước tính ~0.30 cho cả hai tiêu chí. Riêng helpful, số quan sát 0.09 đánh giá thấp vấn đề hơn 3 lần.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng/tiêu chí, 1 người gán nhãn, đã thấy ≥ 1 nhãn sai). Cần nhãn người mới, ≥ 2 người gán, để có held-out thật trước khi tin κ.
