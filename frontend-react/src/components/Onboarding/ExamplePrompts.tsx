import { cn } from '@/lib/cn';

interface ExamplePromptsProps {
  onSendPrompt: (prompt: string) => void;
}

/**
 * Example prompt suggestion cards
 */
export function ExamplePrompts({ onSendPrompt }: ExamplePromptsProps) {
  const prompts = [
    {
      icon: '⚖️',
      title: 'Thử việc tối đa bao lâu?',
      description: 'Thời gian và lương thử việc theo Bộ luật Lao động',
    },
    {
      icon: '🏠',
      title: 'Chủ trọ tự ý tăng giá thuê nhà?',
      description: 'Quy định về thay đổi giá thuê theo Bộ luật Dân sự',
    },
    {
      icon: '🚗',
      title: 'Mức phạt nồng độ cồn hiện hành?',
      description: 'Chế tài xử phạt vi phạm giao thông mới nhất',
    },
    {
      icon: '♻️',
      title: 'Doanh nghiệp có nghĩa vụ tái chế không?',
      description: 'Trách nhiệm tái chế bao bì, sản phẩm theo Luật BVMT',
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl mx-auto">
      {prompts.map((prompt) => (
        <button
          key={prompt.title}
          onClick={() => onSendPrompt(prompt.title)}
          className={cn(
            'group flex items-start gap-3 p-4 text-left',
            'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl',
            'hover:border-green-500 dark:hover:border-green-500 hover:shadow-lg hover:shadow-green-500/10',
            'transition-all duration-200 active:scale-[0.98]'
          )}
        >
          <span className="text-2xl flex-shrink-0">{prompt.icon}</span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-gray-900 dark:text-white group-hover:text-green-600 dark:group-hover:text-green-400 transition-colors">
              {prompt.title}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {prompt.description}
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}
