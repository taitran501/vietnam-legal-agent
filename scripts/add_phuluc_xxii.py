"""Add Phụ lục XXII entries to law.json"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Load existing law.json
with open(ROOT / 'data' / 'law.json', encoding='utf-8') as f:
    data = json.load(f)

# Add Phụ lục XXII entries (recycling rates and specs for products/packaging)
phuluc_xxii_entries = [
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Ắc quy",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Ắc quy (gồm ắc quy chì và các loại khác). Tỷ lệ tái chế bắt buộc: 65%. Quy cách tái chế bắt buộc: Tái chế ra các vật liệu nguyên liệu (chì, axit, nhựa) hoặc hóa chất từ ắc quy. Phải đạt tối thiểu 40% khối lượng vật liệu/hóa chất được thu hồi."
    },
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Pin sạc",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Pin sạc nhiều lần (gồm pin các loại sử dụng cho phương tiện giao thông và pin các loại sử dụng cho các thiết bị điện – điện tử). Tỷ lệ tái chế bắt buộc: 61%. Quy cách tái chế bắt buộc: Tái chế ra các vật liệu, kim loại từ pin (nickel, cobalt, lithium, etc.). Phải đạt tối thiểu 40% khối lượng vật liệu được thu hồi."
    },
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Dầu nhớt",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Dầu nhớt dùng cho động cơ. Tỷ lệ tái chế bắt buộc: 100%. Quy cách tái chế bắt buộc: Tái chế ra dầu tái sinh hoặc các sản phẩm khác có giá trị. Phải đạt tối thiểu 40% khối lượng dầu được thu hồi."
    },
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Săm lốp",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Săm lốp các loại (lốp xe mô tô, ô tô, xe máy, xe tải, etc.). Tỷ lệ tái chế bắt buộc: 47%. Quy cách tái chế bắt buộc: Tái chế ra các sản phẩm (xốp lốp, chế phẩm đệm đường, chế phẩm sân chơi, vv). Phải đạt tối thiểu 40% khối lượng vật liệu được thu hồi."
    },
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Bao bì PET cứng",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Bao bì nhựa — Polyethylene Terephthalate (PET) cứng. Tỷ lệ tái chế bắt buộc: 22%. Quy cách tái chế bắt buộc: Tái chế ra hạt nhựa tái sinh, xơ sợi PE hoặc hóa chất (gồm cả dầu). Phải đạt tối thiểu 40% khối lượng từ 22 tấn PET được thu hồi (tức 8,8 tấn)."
    },
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Bao bì PE/PP",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Bao bì nhựa — Polyethylene (PE) và Polypropylene (PP) (bao bì soft, túi, lớp phủ). Tỷ lệ tái chế bắt buộc: 30%. Quy cách tái chế bắt buộc: Tái chế ra hạt nhựa tái sinh hoặc sản phẩm khác có giá trị. Phải đạt tối thiểu 40% khối lượng vật liệu được thu hồi."
    },
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Điện tử",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Sản phẩm điện – điện tử (tủ lạnh, ti vi, máy tính, điện thoại di động, etc.). Tỷ lệ tái chế bắt buộc: 70%. Quy cách tái chế bắt buộc: Tái chế theo các tiêu chuẩn quốc tế (IEC, CRT, LCD standards). Phải trích xuất kim loại quý, khí lạnh; loại bỏ chất độc hại. Đạt tối thiểu 40% khối lượng vật liệu được thu hồi."
    },
    {
        "Điều": "Phụ lục XXII. Sản phẩm, bao bì phải thực hiện trách nhiệm tái chế — Phương tiện giao thông",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Danh sách đối tượng và tỷ lệ tái chế",
        "Pages": "",
        "Text": "Phương tiện giao thông (xe mô tô 2/3 bánh, xe máy điện, xe ô tô, xe tải, etc.). Tỷ lệ tái chế bắt buộc: 95%. Quy cách tái chế bắt buộc: Tái chế các bộ phận (kim loại, nhựa, kính, dầu, etc.) theo quy chuẩn EU. Phải đạt tối thiểu 85% khối lượng phương tiện được tái sử dụng/tái chế (bao gồm cả năng lượng phục hồi)."
    },
    {
        "Điều": "Phụ lục XXII. Quy định chung về trách nhiệm tái chế",
        "Chương": "PHỤ LỤC XXII",
        "Mục": "Hướng dẫn chung",
        "Pages": "",
        "Text": "Các quy định chung: (1) Tỷ lệ tái chế bắt buộc là % khối lượng tối thiểu phải tái chế trên tổng khối lượng sản xuất/nhập khẩu trong năm. (2) Quy cách tái chế bắt buộc yêu cầu (a) chọn một trong các giải pháp tái chế được phép; (b) đạt tối thiểu 40% khối lượng vật liệu/hóa chất được thu hồi (trừ phương tiện giao thông: 85%). (3) Thực hiện theo một trong hai hình thức: tự tổ chức tái chế hoặc đóng góp tài chính vào Quỹ Bảo vệ môi trường Việt Nam."
    }
]

# Append to the existing meta list
data['meta'].extend(phuluc_xxii_entries)

# Save back
with open(ROOT / 'data' / 'law.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f'✅ Added {len(phuluc_xxii_entries)} Phụ lục XXII entries')
print(f'Total entries now: {len(data["meta"])}')
