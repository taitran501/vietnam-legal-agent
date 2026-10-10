import { useState } from "react";
import { ChatInput } from "@/components/Chat/ChatInput";
import { Icon, type IconName } from "@/components/UI/Icon";
import { cn } from "@/lib/cn";

interface WelcomeScreenProps {
  disabled?: boolean;
  isStreaming: boolean;
  onSendPrompt: (prompt: string) => void;
  onSelectIntent: (intent: string) => void;
  draftText: string;
  onDraftChange: (value: string) => void;
  intentLabel?: string;
  onClearIntent: () => void;
  onStop: () => void;
}

type LegalGoalId = "legal_lookup" | "case_assessment" | "compliance_checklist";

interface LegalGoal {
  id: LegalGoalId;
  icon: IconName;
  label: string;
  placeholder: string;
}

const legalGoals: LegalGoal[] = [
  {
    id: "legal_lookup",
    icon: "search",
    label: "Tra cứu quy định pháp luật",
    placeholder: "Nhập điều khoản, văn bản hoặc vấn đề cần tra cứu…",
  },
  {
    id: "case_assessment",
    icon: "scale",
    label: "Tư vấn tình huống",
    placeholder: "Mô tả ngắn gọn tình huống pháp lý…",
  },
  {
    id: "compliance_checklist",
    icon: "checklist",
    label: "Hồ sơ & thủ tục",
    placeholder: "Bạn muốn thực hiện thủ tục gì?",
  },
];

const intentByGoal: Record<LegalGoalId, string> = {
  legal_lookup: "legal_lookup",
  case_assessment: "case_assessment",
  compliance_checklist: "compliance_checklist",
};

export function WelcomeScreen({
  disabled = false,
  isStreaming,
  onSendPrompt,
  onSelectIntent,
  onStop,
  draftText,
  onDraftChange,
  intentLabel,
  onClearIntent,
}: WelcomeScreenProps) {
  const [focusRequest, setFocusRequest] = useState(0);
  const [selectedGoalId, setSelectedGoalId] = useState<LegalGoalId | null>(
    null,
  );

  const activeGoal = legalGoals.find((goal) => goal.id === selectedGoalId);

  const handleGoalClick = (goal: LegalGoal) => {
    const isSelected = selectedGoalId === goal.id;
    setSelectedGoalId(isSelected ? null : goal.id);
    onSelectIntent(isSelected ? "auto" : intentByGoal[goal.id]);
    setFocusRequest((revision) => revision + 1);
  };

  const handleClearIntent = () => {
    setSelectedGoalId(null);
    onClearIntent();
  };

  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto bg-[#fcfcfa]">
      <div className="mx-auto flex min-h-full w-full max-w-[860px] flex-col items-center px-4 pb-12 pt-[clamp(2.5rem,7vh,5rem)] sm:px-6">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-50 text-[#006a63] shadow-sm ring-1 ring-teal-600/20">
          <Icon name="scale" size={24} />
        </div>

        <h1 className="mt-5 text-center text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl lg:text-4xl">
          Trợ lý Pháp luật Việt Nam
        </h1>

        <p className="mt-2.5 max-w-[580px] text-center text-sm leading-relaxed text-slate-500 sm:text-[15px]">
          Tra cứu căn cứ pháp lý và phân tích tình huống thực tế theo kho văn bản
          đang được cấu hình. Trợ lý sẽ báo rõ khi chưa tìm thấy nguồn phù hợp.
        </p>

        <div className="mt-7 w-full max-w-[760px]">
          <ChatInput
            disabled={disabled}
            focusRequest={focusRequest}
            intentLabel={intentLabel}
            isStreaming={isStreaming}
            onClearIntent={handleClearIntent}
            onSend={onSendPrompt}
            onStop={onStop}
            onValueChange={onDraftChange}
            placeholder={
              activeGoal?.placeholder ||
              "Nhập câu hỏi hoặc mô tả vấn đề pháp lý của bạn…"
            }
            value={draftText}
            variant="welcome"
          />

          <div
            aria-label="Mục tiêu pháp lý"
            className="mt-3 flex flex-wrap justify-center gap-2"
            role="group"
          >
            {legalGoals.map((goal) => {
              const isSelected = selectedGoalId === goal.id;
              return (
                <button
                  className={cn(
                    "inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600",
                    isSelected
                      ? "border-teal-600 bg-teal-50 font-semibold text-teal-800 shadow-sm ring-1 ring-teal-600"
                      : "border-slate-200 bg-white text-slate-600 hover:border-teal-600/40 hover:bg-slate-50 hover:text-teal-900",
                  )}
                  disabled={isStreaming || disabled}
                  key={goal.id}
                  onClick={() => handleGoalClick(goal)}
                  type="button"
                >
                  <Icon name={goal.icon} size={14} />
                  {goal.label}
                </button>
              );
            })}
          </div>

        </div>
      </div>
    </div>
  );
}
