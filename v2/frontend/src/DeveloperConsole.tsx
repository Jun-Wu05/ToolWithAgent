import { RunDiagnostics } from './RunDiagnostics'
import type { Identity } from './api'

type Props = { identity: Identity; identities: Identity[]; onSwitchIdentity: (userId: string) => void; onBack: () => void; theme: 'light' | 'dark'; onToggleTheme: () => void }

export function DeveloperConsole({ identity, identities, onSwitchIdentity, onBack, theme, onToggleTheme }: Props) {
  return <div className="app admin-app">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">T</span><span>ToolWithAgent <small>开发台</small></span></div><nav aria-label="开发导航"><button className="nav-item" onClick={onBack}>对话工作台</button><span className="nav-item selected">Run 诊断</span></nav><div className="identity"><div className="identity-head"><span className="avatar">{identity.display_name?.slice(0, 1) || '开'}</span><span className="identity-name">{identity.display_name}<small>{identity.role}</small></span></div>{identities.length > 1 && <select aria-label="开发身份切换" value={identity.id} onChange={event => onSwitchIdentity(event.target.value)}><option value={identity.id}>{identity.display_name} ({identity.role})</option>{identities.filter(item => item.id !== identity.id).map(item => <option key={item.id} value={item.id}>{item.display_name} ({item.role})</option>)}</select>}</div></aside>
    <main className="workspace"><header className="workspace-header"><div><h1>开发台</h1><p>查看 Run 的执行证据与脱敏诊断包</p></div><div className="header-actions"><button className="icon-button" aria-label={theme === 'light' ? '切换深色主题' : '切换浅色主题'} onClick={onToggleTheme}>{theme === 'light' ? '深色主题' : '浅色主题'}</button></div></header><div className="conversation-content"><RunDiagnostics /></div></main>
  </div>
}
