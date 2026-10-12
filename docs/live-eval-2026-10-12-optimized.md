# Eval sau tối ưu độ trễ và MCP — 12/10/2026

Bản frozen giữ được **8/8 tiêu chí hành vi**, nhưng **không đạt tổng thể** vì terminal response chứa nhiều `HARNESS_RESULT`. Wall-clock tăng từ khoảng 29 lên **36.413 phút**, total token tăng **47.1%** trong mẫu đã đo. Lựa chọn MCP mô phỏng đạt 5/5; hai probe browser frozen không gợi ý kết thúc blocked, probe chờ khởi tạo rồi gửi prompt không hoàn thành độc lập. Chưa có bằng chứng tối ưu tốc độ hoặc MCP tự thực thi trọn vẹn.

## Phạm vi so sánh

Baseline nằm trong [artifact đã lọc](../evals/results/2026-10-12-live.json) và [báo cáo trước](live-eval-2026-10-12.md). Kết quả đợt tối ưu được lưu trong [artifact đối chứng đã lọc](../evals/results/2026-10-12-optimized.json). Cùng model `gemini-3.8-flash-high`, dùng Antigravity first-party qua `agy`. Bài waiting list gồm bốn yêu cầu tự nhiên tích lũy, không workflow reminder hoặc continuation tự động.

Các thay đổi giảm workflow lồng ở leaf, để parent chạy kiểm tra cuối theo phạm vi cần thiết và chọn route theo tác động đã kiểm tra. MCP bổ sung khám phá capability công khai đã lọc, đọc schema cần thiết và gọi native tool; main thực thi trừ khi leaf thực sự có đúng tool. Quyền `Ask` và xử lý từ chối được giữ nguyên. Runner có transport stream tùy chọn để chẩn đoán.

Đây là một mẫu mỗi cấu hình, chưa có phân bố độ trễ hoặc tỉ lệ thành công. CLI được quan sát từ 1.3.2 sang 1.3.3 giữa các probe; transport, policy và context cũng thay đổi. Không quy kết nhân quả cho một sửa đổi riêng lẻ.

## Kết quả đối chứng đã đo

| Chỉ số | Baseline | Frozen trước sửa gate |
|---|---|---|
| Hành vi bốn lượt độc lập | 8/8, test công khai đạt | 8/8, test công khai đạt |
| Phạm vi thay đổi | Không vượt phạm vi | `scope_error: null` |
| Kết quả tổng thể | Đạt | Không đạt: nhiều `HARNESS_RESULT` |
| Route | Cuối: `IMPLEMENT` | Cả bốn lượt: `IMPLEMENT` |
| Wall-clock | Khoảng 29 phút | 2,184.796 giây = 36.413 phút |
| Usage cuối `total_tokens` | 1,504,646 | 2,213,413; tăng khoảng 47.1% |
| Lựa chọn MCP mô phỏng | 5/5; 23.262 giây subprocess | 5/5; 41.991 giây subprocess, 42.453 giây toàn runner |
| Browser hoàn thành | Đạt có hỗ trợ inventory và năm lần cấp quyền riêng | Hai probe blocked; probe idle-start không hoàn thành độc lập; cả ba không browser hit |

Artifact `optimized-frozen-multiturn.json` có `claimed: null`, `completion_claim_error: "expected exactly one HARNESS_RESULT claim"`: ít nhất hai claim ngoài code fence. Giữ nguyên `success: false`; không chấm lại lần đã chạy. `false_complete: false` không thay thế yêu cầu claim hợp lệ. Tám tiêu chí của runner là các nhóm hành vi cố định ngoài fixture model được sửa; số AC model tự chọn không phải điểm độc lập.

| Lượt | Route | Wall-clock subprocess |
|---|---|---:|
| 1 | `IMPLEMENT` | 815.310 giây |
| 2 | `IMPLEMENT` | 382.970 giây |
| 3 | `IMPLEMENT` | 385.701 giây |
| 4 | `IMPLEMENT` | 599.917 giây |

Deadline frozen là **1,800 giây/lượt**, tăng từ 900 giây/lượt của chẩn đoán chưa hoàn thành. Đây là thay đổi điều kiện chạy, không phải bằng chứng giảm độ trễ. Route về `IMPLEMENT` chưa tạo lợi ích tốc độ quan sát được.

Usage tích lũy ở result cuối:

| Trường | Baseline | Frozen |
|---|---:|---:|
| `input_tokens` | 1,410,072 | 2,097,484 |
| `output_tokens` | 94,574 | 115,929 |
| `thinking_tokens` | 59,927 | 51,205 |
| `cache_read_tokens` | 23,539,714 | 19,327,057 |
| `total_tokens` | 1,504,646 | 2,213,413 |

Không cộng usage các lượt vốn đã tích lũy, không cộng cache vào total và không quy đổi thành chi phí. Điểm cuối 8/8 xác nhận sản phẩm cuối giữ hành vi tích lũy, không chứng minh mọi trạng thái trung gian đã đúng.

## MCP thật: khám phá và thực thi

Probe `optimized-frozen-browser.json` tự khám phá schema với **0 gợi ý inventory/tool**, có một lần thử native MCP và một browser builtin fallback. Dispatcher trả `unknown tool: "call_mcp_tool"` và `unknown tool: "browser_navigate"`. Không có thẻ `Ask`, cấp quyền hoặc browser page/confirmation hit; model báo **blocked**, hai giá trị cần kiểm chứng đều chưa được xác nhận.

Probe thứ hai `optimized-frozen-browser-retry.json` cũng có **0 gợi ý, lời gọi tool, cấp quyền và browser hit**. Model báo không có invoker native, nhưng **inventory thiếu tool chưa được chứng minh độc lập**. Operator mở `/mcp` sau tác vụ và thấy Playwright ready; trạng thái sau tác vụ không chứng minh khả dụng trong lúc model chạy.

Không quan sát bypass quyền hoặc thay browser bằng đọc source/API. Báo blocked là trung thực nhưng tác vụ vẫn chưa đạt. Trở ngại quan sát khác baseline headless `Ask` soft-deny: probe frozen thứ nhất lỗi ở dispatch trước khi xuất hiện yêu cầu quyền.

Health check Playwright trực tiếp baseline đạt; init công khai riêng quảng bá invoker và health check model riêng trả đúng câu thử. Những ngữ cảnh riêng này không bảo đảm inventory của tác vụ browser giống hệt. Hai thời gian quan sát browser frozen 394 và 274 giây gồm chờ/quan sát của operator, **loại khỏi so sánh độ trễ**.

**Probe idle-start không chứng minh phục hồi.** Với gate cuối `f79e28...`, CLI tương tác được khởi tạo rồi chờ 30 giây trước khi gửi prompt tự nhiên một lần; không gợi ý inventory/tool, không cấp quyền file/MCP và không mở `/mcp` trong tác vụ. Model tự khám phá skill, metadata Playwright cụ thể và schema `browser_snapshot.json`, nhưng không quan sát dispatch tool, thẻ `Ask` hoặc browser hit.

Output yên hơn 60 giây rồi operator đóng CLI; thời gian quan sát là **276.563 giây**. Không xác nhận độc lập được terminal handoff: `terminal_completion_independently_confirmed: false`, `final_reported_blocked: null`. Phân loại là **chẩn đoán không hoàn thành/không thành công**, không gọi là blocked đã xác nhận. Loại thời gian này khỏi so sánh độ trễ. Việc chờ trước prompt không chứng minh phục hồi và không xác định timing khởi tạo invoker là nguyên nhân.

## Aggregation terminal response và sửa gate

Chẩn đoán công khai `aggregation-probe.json` dùng synthetic Stop continuation, transport process/stream-json: có **hai step `agent_response` riêng theo thứ tự**, mỗi step chứa sentinel khác nhau, còn terminal response chứa **cả hai**. Một lần hook yêu cầu tiếp tục, hai lần hook chạy; terminal `SUCCESS`, exit 0, 18.66 giây, không timeout. Điều này **chứng minh aggregation trong chính probe này**.

Nó không chứng minh aggregation là nguồn của các claim trùng trong bài bốn lượt, không chứng minh model cố ý bỏ qua protocol, và không thay đổi điểm frozen đã đo. Cần phân biệt câu trả lời ở từng step với chuỗi response mà CLI tổng hợp.

Một lỗi source riêng đã xác nhận: gate trước đó không đếm nhất quán `HARNESS_RESULT` có khoảng trắng đầu dòng. Bản sửa strip khoảng trắng trước khi đếm. Hai regression test với bốn subcase thất bại trước sửa và đạt sau sửa; **104 test liên quan** đạt. Lỗi này **chưa được chứng minh là nguyên nhân gốc của kết quả live**; bản sửa chưa có eval bốn lượt live mới để xác nhận tác động.

## Phiên bản và kiểm chứng source

Policy/agent/skill behavior SHA-256 của frozen: `49faa00a7074fd4628557dbb5ee4f5a76d3ca45de9fc8aa1779bf19c39941ab5`, source khớp bản cài. Digest này **không bao gồm runtime Python**, nên phải phân biệt runtime trước/sau sửa gate:

| Thành phần | SHA-256 |
|---|---|
| Gate dùng trong bài bốn lượt frozen | `d88a778c7d866fbbe34da732e15eaa55089f4124f7569352c64554312af45cdd` |
| Gate cuối đã cài **sau** bài bốn lượt | `f79e28aaaaaeced2d32dd92044a02d7090b8decdf90b2b291e37c20215900dd8` |
| Lifecycle guard của frozen | `df8be6789564a744ac5b22558e326380134b6d4d656233d5ff8982fbfcff67f3` |

Trước sửa gate: **271 test Python (3 skip)** và **15 test Node** đạt. Sau sửa: **273 test Python (3 skip)** và **15 test Node** đạt; installer exit 0. Doctor ở lần kiểm tra môi trường trước đó exit 0. Không đổi quyền toàn cục.

## Các chẩn đoán trung gian không tính là benchmark hoàn chỉnh

Các quan sát dưới đây lấy từ JSON đã lọc trong `.harness-eval.live-results/`, không dùng raw log/cấu hình riêng tư. Chúng dùng các bản trung gian, không gộp vào số liệu frozen.

| Chẩn đoán | Kết quả và giới hạn |
|---|---|
| Chỉ có tên ứng viên browser | 184 giây, không browser hit; chưa khám phá định nghĩa tool |
| Bốn lượt, bản đầu | Lượt 1: 774.038 giây, `COMPLEX_IMPLEMENT`; operator dừng, không có điểm toàn bài |
| Bốn lượt stream | `EvalError` sau 451.624 giây, chưa có turn summary |
| Process deadline 900 giây/lượt | Khoảng 15 phút, không có điểm cuối; observer không giữ loại exception |
| Khởi chạy process khác | Nonzero ở lượt 1 sau 0.176 giây; không phải tốc độ hoàn thành |
| Protocol stream riêng | Terminal `ERROR` sau khoảng 156 giây, không hoàn thành lượt |
| Browser schema, operator ngắt | Tới `browser_navigate`, hai lần cấp quyền đọc README; ngắt khi xem quyền, chưa đạt |
| Browser khám phá lệch phạm vi | Ít nhất 21 lần khám phá file, chín lần cấp quyền đọc file công khai, không hit; operator dừng |
| Lựa chọn mô phỏng bản trung gian | 5/5, 28.502 giây; không phải mẫu frozen |

Digest trung gian `4e59d956ffa2e7360d65bfa78a453d1fedc49dd311d396517c1b337f9cb4a0c6` thuộc lượt đầu bị dừng; `5861738b8fc6588918250580af88d5d8a713034b3bcf0e88a27f70aa09ade25c` thuộc lỗi stream/browser bị ngắt. Hook timing riêng: năm mẫu, median **75.203 ms**, thêm **1,019 byte** context, không gọi model và không có baseline. Đây không phải số đo độ trễ workflow hoặc bằng chứng speedup.

Kết quả hiện có xác nhận giữ chất lượng hành vi 8/8, đồng thời ghi nhận protocol chưa đạt, thời gian/token tăng và MCP tự thực thi chưa thành công. Bản sửa gate có kiểm chứng source; chưa đủ bằng chứng rằng nó giải quyết lỗi live hoặc cải thiện tốc độ.
