# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Output (rút gọn):
```
== seeded_regression C-002@11  lab8 grader: FAIL (status resolved != denied)
   1 handoff            {"task": "check_applicable_policy", ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-202", "status": "delivered", "delay_days": 2, ...}}}
   3 model_override     {"delay_days": 5}
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
   5 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   6 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."}
  refund_vnd     ledger=20000    label=0   <-- differs
  status         result=resolved label=denied

== fixed C-002@11  lab8 grader: PASS (ok)
   2 investigator       {... "delay_days": 2 ...}
   3 quote              {"amount_vnd": 0, "reason": "no_entitlement", "clause_ids": []}
   4 reply              {"text": "Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."}
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, report `E-seeded_regression-20261118-7009` (row `E-002`, seed 11). Cùng lỗi trên baseline: `swarm C-002@55`, report `E-swarm-20261118-7009` |
| Triệu chứng | `pass_rate` FAIL (`status resolved != denied`), `refund_amount_correct` FAIL (ledger 20.000đ, nhãn 0), `db_fact_kept` FAIL (1 override event), `proposal_matches_policy` FAIL (20.000 ≠ 0). Reply "đã hoàn 20.000đ" khớp ledger, nên `reply_matches_ledger` xanh: reply trôi chảy và "thật", nhưng khoản hoàn sai từ gốc. |
| Bước sai đầu tiên | **Event 3 · `model_override` · `{"delay_days": 5}`** |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` chỉ cấp tool read-only, đúng contract. Event 2 `investigator` đọc DB O-202 đúng (`delay_days: 2`, `status: delivered`). Event 3 thay số 2 của DB bằng số 5 khách tự khai ("Đơn giao trễ 5 ngày"). Event 4 quote 20.000đ chỉ là hệ quả: `compute_compensation` tính đúng trên đầu vào đã bị sửa. |
| Failure mode | **FM-03** ticket_trust (`docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-002@11`: không có event `model_override`. Quote dùng `delay_days: 2` → `no_entitlement`, 0đ → `denied`, ledger 0. Lab 8 PASS. |
| Regression test | `tests/test_lab9_trace_case.py`: `test_lab9_trace_case_first_wrong_step_is_model_override` assert event 3 là `model_override {"delay_days": 5}` với DB = 2, và `fixed` không có event đó. `test_lab9_trace_case_graders_fail_buggy_and_pass_fixed` assert `DbFactKept`, `RefundAmountCorrect`, `ProposalMatchesPolicy` và grader Lab 8 **fail trên `seeded_regression`, pass trên `fixed`**. Đã chạy: xanh (nằm trong `-k "lab9 and not advanced"` của CI). Item E-002 trong eval set ghi `provenance.from_trace = "R-swarm-C-002-s55"`. |
| Chưa chắc chắn | Trace không ghi *vì sao* agent tin ticket (MockLLM không có lời giải thích; với swarm gốc là luật `seed % 5 == 0`). Với LLM thật, cần log prompt hoặc lý do để phân biệt "parse sai" với "cố ý tin khách". Trace cũng không ghi kết quả `issue_refund` của host, nên phải đọc ledger mới biết tiền đã đi. Biến thể `quiet_override` cùng lỗi nhưng không ghi event 3, khi đó bước sai chỉ suy ra được từ quote ≠ policy (`proposal_matches_policy`), không trỏ được số event. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai (case này: reply khớp ledger nhưng ledger sai).
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
