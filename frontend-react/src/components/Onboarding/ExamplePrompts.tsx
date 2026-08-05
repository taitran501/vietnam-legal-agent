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
      icon: '📜',
      title: 'Nghị định 08/2022 là gì?',
      description: 'Tổng quan về nghị định EPR',
    },
    {
      icon: '♻️',
      title: 'Điều 77 quy định gì về tái chế?',
      description: 'Nghĩa vụ tái chế sản phẩm, bao bì',
    },
    {
      icon: '📊',
      title: 'Tỷ lệ tái chế bao bì nhựa PE/PP?',
      description: 'Mức tỷ lệ tái chế bắt buộc',
    },
    {
      icon: '🏭',
      title: 'Nghĩa vụ của nhà sản xuất khi làm EPR?',
      description: 'Trách nhiệm của doanh nghiệp',
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
