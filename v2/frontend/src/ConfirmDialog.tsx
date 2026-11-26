import { MappingDialog } from './MappingDialog'

// window.confirm 的统一替换外壳（#470）：复用 MappingDialog 的焦点圈、Esc 关闭与焦点还原。
export function ConfirmDialog({ title, message, confirmLabel = '确认', onConfirm, onCancel }: {
  title: string
  message: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  return <MappingDialog title={title} onClose={onCancel}>
    <p>{message}</p>
    <div className="mapping-actions">
      <button className="button-text" data-dialog-cancel onClick={onCancel}>取消</button>
      <button className="button-text" onClick={onConfirm}>{confirmLabel}</button>
    </div>
  </MappingDialog>
}
