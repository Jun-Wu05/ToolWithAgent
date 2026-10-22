import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { StandardField } from './api'

type Props = { label: string; value: string; fields: StandardField[]; source: string; disabled: boolean; onSelect: (value: string) => void }

export function StandardFieldPicker({ label, value, fields, source, disabled, onSelect }: Props) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const restore = useRef(false)
  const menuId = useId()
  useEffect(() => { if (!open && !disabled && restore.current) { trigger.current?.focus({ preventScroll: true }); restore.current = false } }, [disabled, open])
  return <>
    <button ref={trigger} type="button" className="mapping-select field-picker-trigger" role="combobox" aria-label={label} aria-expanded={open} aria-controls={open ? menuId : undefined} aria-haspopup="dialog" disabled={disabled} onClick={() => setOpen(true)}><span>{value || '未映射'}</span><span aria-hidden="true">⌄</span></button>
    {open && !disabled && trigger.current && <FieldMenu menuId={menuId} anchor={trigger.current} label={label} value={value} fields={fields} source={source} onClose={() => setOpen(false)} onSelect={next => { restore.current = true; setOpen(false); if (next !== value) onSelect(next) }} />}
  </>
}

function FieldMenu({ menuId, anchor, label, value, fields, source, onClose, onSelect }: Omit<Props, 'disabled'> & { menuId: string; anchor: HTMLButtonElement; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(30)
  const [position, setPosition] = useState<{ left: number; top?: number; bottom?: number; width: number; maxHeight: number }>({ left: 12, top: 12, width: 320, maxHeight: 320 })
  const search = useRef<HTMLInputElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const id = useId()
  useLayoutEffect(() => {
    const place = () => {
      const rect = anchor.getBoundingClientRect()
      const width = Math.min(360, innerWidth - 24)
      const below = Math.max(0, innerHeight - rect.bottom - 18), above = Math.max(0, rect.top - 18)
      const down = below >= Math.min(300, innerHeight - 24) || below >= above
      setPosition({ left: Math.max(12, Math.min(rect.left, innerWidth - width - 12)), width,
        top: down ? Math.max(12, rect.bottom + 6) : undefined, bottom: down ? undefined : Math.max(12, innerHeight - rect.top + 6), maxHeight: Math.min(320, down ? below : above) })
    }
    const scroll = (event: Event) => { if (!panel.current?.contains(event.target as Node)) place() }
    place(); search.current?.focus({ preventScroll: true })
    const frame = requestAnimationFrame(place)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(place)
    observer?.observe(anchor)
    window.addEventListener('resize', place); window.addEventListener('scroll', scroll, true)
    return () => { cancelAnimationFrame(frame); observer?.disconnect(); window.removeEventListener('resize', place); window.removeEventListener('scroll', scroll, true); if (anchor.isConnected) anchor.focus({ preventScroll: true }) }
  }, [anchor])
  const filtered = fields.filter(field => (field.name + ' ' + field.category).toLowerCase().includes(query.trim().toLowerCase()))
  return createPortal(<div className="field-picker-layer"><div className="field-picker-mask" onClick={onClose} /><div ref={panel} id={menuId} className="field-picker-menu" role="dialog" aria-modal="true" aria-label={'选择' + label} style={position} onKeyDown={event => {
    event.stopPropagation()
    if (event.nativeEvent.isComposing) return
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
    if (event.key === 'Enter' && (event.target as HTMLElement).matches('[role=option]:not(:disabled)')) { event.preventDefault(); (event.target as HTMLButtonElement).click(); return }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      const options = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role=option]:not(:disabled)')]
      if (!options.length) return
      event.preventDefault()
      const index = options.indexOf(document.activeElement as HTMLButtonElement)
      options[index < 0 ? event.key === 'ArrowDown' ? 0 : options.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length]?.focus()
    }
    if (event.key === 'Tab') {
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input')]
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus() }
      else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus() }
    }
  }}>
    <header><strong>{source}</strong><button type="button" aria-label="关闭标准字段选择" onClick={onClose}>×</button></header>
    <label className="field-picker-search"><span className="sr-only">搜索标准字段</span><input ref={search} aria-controls={id} placeholder="搜索标准字段或分类" value={query} onChange={event => { setQuery(event.target.value); setLimit(30) }} /></label>
    <div className="field-picker-options" role="listbox" id={id} aria-label="标准字段候选">
      <button type="button" role="option" aria-selected={!value} onClick={() => onSelect('')}>未映射<small>保留原始字段</small></button>
      {filtered.slice(0, limit).map(field => <button type="button" role="option" key={field.name} aria-selected={value === field.name} disabled={!!field.disabled_reason} onClick={() => onSelect(field.name)}><span>{field.name}{value === field.name && ' ✓'}</span><small>{field.occupied_by && field.occupied_by !== source ? '已被 ' + field.occupied_by + ' 占用' : field.category}{field.disabled_reason && ' · 不可选择：' + (field.disabled_reason === 'mapping_occupant_not_editable' ? '占用字段由平台维护' : field.disabled_reason === 'mapping_target_invalid' ? '不是可映射标准字段' : '当前目录不允许此项')}</small></button>)}
      {!filtered.length && <p>没有符合条件的标准字段。</p>}
      {filtered.length > limit && <button type="button" className="button-text" onClick={() => setLimit(limit + 30)}>再显示30项</button>}
    </div><footer>显示 {Math.min(limit, filtered.length)} / {filtered.length} 项 · 选择后保存草稿</footer>
  </div></div>, document.body)
}
