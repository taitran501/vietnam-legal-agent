interface WelcomeScreenProps {
  onSendPrompt: (prompt: string) => void;
}

/** Entry state for the three bounded tasks exposed by the compliance copilot. */
export function WelcomeScreen({ onSendPrompt }: WelcomeScreenProps) {
  const actions = [
    {
      icon: '📚',
      title: 'Tra cứu quy định',
      body: 'Hỏi về một Điều, nghĩa vụ hoặc khái niệm EPR.',
      prompt: 'Điều 77 quy định gì về trách nhiệm tái chế?',
    },
    {
      icon: '🔎',
      title: 'Đánh giá nghĩa vụ',
      body: 'Xác định sơ bộ doanh nghiệp có thể cần thực hiện gì.',
      prompt: 'Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?',
    },
    {
      icon: '✓',
      title: 'Lập checklist',
      body: 'Tạo danh sách việc cần chuẩn bị, có nguồn để đối chiếu.',
      prompt: 'Lập checklist tuân thủ EPR cho nhà nhập khẩu bao bì giấy tại Việt Nam.',
    },
  ];

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto bg-[radial-gradient(circle_at_top,_#dff7f3,_#f8fafc_46%)] p-8">
      <div className="w-full max-w-3xl text-center">
        <div className="mb-8">
          <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-700 to-cyan-700 text-4xl text-white shadow-2xl shadow-teal-700/25">
            ⚖️
          </div>
          <h2 className="text-3xl font-bold text-slate-950">EPR Compliance Copilot</h2>
          <p className="mx-auto mt-3 max-w-xl text-base leading-7 text-slate-600">
            Trợ lý tra cứu và chuẩn bị tuân thủ EPR, với kết quả có nguồn để bạn đối chiếu.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 text-left md:grid-cols-3">
          {actions.map((action) => (
            <button
              key={action.title}
              onClick={() => onSendPrompt(action.prompt)}
              className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-teal-500 hover:shadow-md"
            >
              <span className="text-2xl">{action.icon}</span>
              <h3 className="mt-4 text-sm font-semibold text-slate-950">{action.title}</h3>
              <p className="mt-1 text-sm leading-5 text-slate-600">{action.body}</p>
            </button>
          ))}
        </div>
        <p className="mt-8 text-xs text-slate-500">
          Kết quả hỗ trợ tra cứu, không thay thế tư vấn pháp lý hoặc hồ sơ doanh nghiệp.
        </p>
      </div>
    </div>
  );
}
