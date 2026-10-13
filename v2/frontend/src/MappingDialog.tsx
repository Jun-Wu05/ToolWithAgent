import { useEffect, useRef, type ReactNode } from 'react'

// One focus boundary for the replacement and pending-message choices.
export function MappingDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const element = dialog.current!
    element.querySelector<HTMLButtonElement>('[data-dialog-cancel]')?.focus()
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close.current(); return }
      if (event.key !== 'Tab') return
      const controls = [...element.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')]
      if (!controls.length) { event.preventDefault(); element.focus(); return }
      const first = controls[0], last = controls.at(-1)
      if (event.shiftKey && (document.activeElement === first || document.activeElement === element)) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === element)) { event.preventDefault(); first?.focus() }
    }
    element.addEventListener('keydown', keyboard)
    return () => { element.removeEventListener('keydown', keyboard); if (previous?.isConnected) previous.focus() }
  }, [])
  return <div className="mapping-dialog-backdrop"><dialog ref={dialog} tabIndex={-1} open aria-modal="true" aria-label={title} className="mapping-dialog"><h2>{title}</h2>{children}</dialog></div>
}
