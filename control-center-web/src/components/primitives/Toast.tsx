import * as ToastPrimitive from '@radix-ui/react-toast';
import { X } from 'lucide-react';
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { IconButton } from './IconButton';

export type ToastTone = 'info' | 'success' | 'warning' | 'danger';
export type ToastMessage = {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
  duration: number;
};

type PushToastInput = Omit<ToastMessage, 'id' | 'duration' | 'tone'> & {
  duration?: number;
  tone?: ToastTone;
};

const ToastContext = createContext<((message: PushToastInput) => number) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ToastMessage[]>([]);
  const nextId = useRef(1);

  const pushToast = useCallback((input: PushToastInput) => {
    const id = nextId.current++;
    setMessages((current) => [
      ...current,
      {
        id,
        title: input.title,
        description: input.description,
        duration: input.duration ?? 4_000,
        tone: input.tone ?? 'info',
      },
    ]);
    return id;
  }, []);

  const value = useMemo(() => pushToast, [pushToast]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider label="通知 ({hotkey})" swipeDirection="right">
        {children}
        {messages.map((message) => (
          <ToastPrimitive.Root
            key={message.id}
            className="ui-toast"
            data-tone={message.tone}
            duration={message.duration}
            onOpenChange={(open) => {
              if (!open) setMessages((current) => current.filter((item) => item.id !== message.id));
            }}
          >
            <div className="ui-toast__copy">
              <ToastPrimitive.Title className="ui-toast__title">{message.title}</ToastPrimitive.Title>
              {message.description ? (
                <ToastPrimitive.Description className="ui-toast__description">
                  {message.description}
                </ToastPrimitive.Description>
              ) : null}
            </div>
            <ToastPrimitive.Close asChild>
              <IconButton icon={<X size={15} />} label="关闭通知" size="small" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="ui-toast__viewport" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const pushToast = useContext(ToastContext);
  if (!pushToast) throw new Error('useToast must be used inside ToastProvider');
  return pushToast;
}
