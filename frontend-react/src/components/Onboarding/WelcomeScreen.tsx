import { ExamplePrompts } from './ExamplePrompts';

interface WelcomeScreenProps {
  onSendPrompt: (prompt: string) => void;
}

/**
 * Beautiful welcome screen with example prompts
 */
export function WelcomeScreen({ onSendPrompt }: WelcomeScreenProps) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto overscroll-y-contain p-8 animate-in fade-in zoom-in-95 duration-500">
      <div className="max-w-2xl w-full text-center">
        {/* Logo and welcome message */}
        <div className="mb-8">
          <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center text-white text-4xl shadow-2xl shadow-green-500/30">
            ⚖️
          </div>
          <h2 className="text-3xl font-bold text-gray-900 dark:text-white mb-3">
            Xin chào! Tôi có thể giúp gì?
          </h2>
          <p className="text-lg text-gray-600 dark:text-gray-400">
            Trợ lý AI về Luật Trách nhiệm Nhà sản xuất (EPR) & Nghị định 08/2022/NĐ-CP
          </p>
        </div>

        {/* Example prompts */}
        <ExamplePrompts onSendPrompt={onSendPrompt} />

        {/* Features */}
        <div className="mt-12 grid grid-cols-3 gap-6">
          <div className="text-center">
            <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
              <svg className="w-6 h-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-1">
              Hỏi đáp pháp lý
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Trả lời dựa trên văn bản pháp luật
            </p>
          </div>

          <div className="text-center">
            <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-green-50 dark:bg-green-900/20 flex items-center justify-center">
              <svg className="w-6 h-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-1">
              Tài liệu tham khảo
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Nguồn gốc rõ ràng, dễ kiểm chứng
            </p>
          </div>

          <div className="text-center">
            <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
              <svg className="w-6 h-6 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-1">
              Hỏi đáp thông thường
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Giải đáp nhanh các câu hỏi phổ biến
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
