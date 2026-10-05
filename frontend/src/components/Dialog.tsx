import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

export function Dialog({ title, eyebrow, children, onClose, wide = false }: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    dialog.showModal();
    return () => {
      dialog.close();
      previous?.focus();
    };
  }, []);
  return <dialog ref={ref} className={`dialog ${wide ? 'dialog-wide' : ''}`} aria-labelledby="dialog-title"
    onCancel={(event) => { event.preventDefault(); closeRef.current(); }}
    onClick={(event) => { if (event.target === event.currentTarget) closeRef.current(); }}>
    <header className="dialog-header">
      <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2 id="dialog-title">{title}</h2></div>
      <button className="icon-button" aria-label={`Close ${title}`} onClick={onClose}><X size={21} /></button>
    </header>
    <div className="dialog-content">{children}</div>
  </dialog>;
}
