import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {App} from './App'
import {api, saveDownload, type Conversation} from './api'
vi.mock('./api', () => ({saveDownload: vi.fn(), api: Object.fromEntries(['me','identities','selectIdentity','conversations','conversation','eventsUrl','sendMessage','confirmationToken','confirmRun','run','artifactContent','mappingDownload','mappingView','mappingDraft'].map(name => [name, vi.fn()]))}))
class Events {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror = null
  static instances: Events[] = []
  close() {}
  constructor() {Events.instances.push(this)}
}
const owner = {id:'u1', display_name:'原身份', role:'user' as const}
const other = {id:'u2', display_name:'新身份', role:'user' as const}
const summary = {id:'c1', title:'确认任务', created_at:'', updated_at:''}
const detail: Conversation = {...summary, messages:[], files:[], runs:[{id:'r1', status:'waiting_confirmation'}]}
let publish: (value: {id:string; status:string}) => void
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); Events.instances=[]
  vi.stubGlobal('EventSource', Events)
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.mocked(api.me).mockResolvedValue(owner)
  vi.mocked(api.identities).mockResolvedValue({items:[owner,other]})
  vi.mocked(api.conversations).mockResolvedValue({items:[summary]})
  vi.mocked(api.conversation).mockResolvedValue(detail)
  vi.mocked(api.mappingView).mockResolvedValue({artifact_id:'', sub_rules:[], sub_rule_id:'', items:[], total:0, page:1, page_size:50, sample_line_reference:'log_entry'})
  vi.mocked(api.mappingDraft).mockResolvedValue({id:'', conversation_id:'', base_artifact_id:'', revision:0, status:'active', changed_count:0, operation_count:0, operations:[], base_current:true, apply_run_id:null, applied_artifact_id:null})
  vi.mocked(api.eventsUrl).mockReturnValue('/events')
  vi.mocked(api.confirmationToken).mockResolvedValue({token:'approval', checkpoint_revision:1, kind:'business_plan', payload:{question:'确认导出？', operations:['export']}})
  vi.mocked(api.confirmRun).mockResolvedValue({id:'r1',status:'queued'})
  vi.mocked(api.run).mockReturnValue(new Promise(resolve => {publish=resolve}))
  vi.mocked(api.sendMessage).mockResolvedValue({id:'m1',actor:'user',content:'下一轮请求'})
})
afterEach(() => {cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals()})
async function start() {
  render(<App />); await screen.findByRole('heading',{name:'确认任务'})
  fireEvent.change(screen.getByLabelText('消息内容'),{target:{value:'下一轮请求'}})
  fireEvent.click(screen.getByRole('button',{name:'发送'}))
  const dialog=await screen.findByRole('dialog')
  await within(dialog).findByText('确认导出？')
  fireEvent.click(within(dialog).getByRole('button',{name:'确认完成后发送'}))
  await waitFor(() => expect(api.run).toHaveBeenCalledWith('r1'))
}
it('keeps queued text across App SSE refresh and sends once after publication',async () => {
  await start()
  vi.mocked(api.conversation).mockResolvedValue({...detail,runs:[{id:'r1',status:'queued'}]})
  const reads=vi.mocked(api.conversation).mock.calls.length
  await act(async () => Events.instances.at(-1)!.onmessage?.(new MessageEvent('message',{data:JSON.stringify({sequence:1,event_type:'run_queued',payload:{run_id:'r1',status:'queued'}})})))
  await waitFor(() => expect(vi.mocked(api.conversation).mock.calls.length).toBeGreaterThan(reads))
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(screen.getByLabelText('消息内容')).toHaveValue('下一轮请求')
  expect(api.sendMessage).not.toHaveBeenCalled()
  vi.mocked(api.conversation).mockResolvedValue({...detail,runs:[{id:'r1',status:'succeeded'}]})
  await act(async () => publish({id:'r1',status:'succeeded'}))
  await waitFor(() => expect(api.sendMessage).toHaveBeenCalledExactlyOnceWith('c1','下一轮请求'))
})
it('drops old confirmation completion after identity switch',async () => {
  await start()
  const next={...summary,id:'c2',title:'新身份会话'}
  vi.mocked(api.selectIdentity).mockResolvedValue(other)
  vi.mocked(api.me).mockResolvedValue(other)
  vi.mocked(api.conversations).mockResolvedValue({items:[next]})
  vi.mocked(api.conversation).mockResolvedValue({...next,messages:[],files:[],runs:[]})
  fireEvent.change(screen.getByLabelText('开发身份切换'),{target:{value:'u2'}})
  await screen.findByRole('heading',{name:'新身份会话'})
  fireEvent.change(screen.getByLabelText('消息内容'),{target:{value:'新身份输入'}})
  await act(async () => publish({id:'r1',status:'succeeded'}))
  expect(api.sendMessage).not.toHaveBeenCalled()
  expect(screen.getByLabelText('消息内容')).toHaveValue('新身份输入')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})


it('clears a waiting plan directly while preserving text and ordinary send confirmation',async () => {
  render(<App />); await screen.findByRole('heading',{name:'确认任务'})
  fireEvent.change(screen.getByLabelText('消息内容'),{target:{value:'未发送的下一轮'}})
  fireEvent.click(screen.getByRole('button',{name:'发送'}))
  expect(await screen.findByRole('dialog')).toHaveTextContent('发送前处理执行方案')
  expect(api.sendMessage).not.toHaveBeenCalled()
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'返回处理'}))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  vi.mocked(api.conversation).mockResolvedValue({...detail,runs:[{id:'r1',status:'cancelled'}]})
  fireEvent.click(screen.getByRole('button',{name:'清空业务数据（保留历史）'}))
  await waitFor(() => expect(api.sendMessage).toHaveBeenCalledExactlyOnceWith('c1','清空数据',expect.any(String)))
  await screen.findByText('清空业务数据已排队，历史结果和未发送文本会保留。')
  expect(screen.getByLabelText('消息内容')).toHaveValue('未发送的下一轮')
  expect(api.confirmRun).not.toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('keeps inactive files historical without execute entries but preserves owner result content and download',async () => {
  const artifact={id:'history-enum',run_id:'old-run',kind:'enum_values' as const,status:'stale',current:false,summary:{item_count:1}}
  vi.mocked(api.conversation).mockResolvedValue({...detail,runs:[],files:[{id:'old-file',name:'history.txt',active:false,parse_status:'succeeded',mapping_eligible:true}],artifacts:[artifact]})
  vi.mocked(api.artifactContent).mockResolvedValue({values:['本人历史真实值']})
  const download={name:'enumvalues_20261014_100000.json',blob:new Blob(['历史导出'])}
  vi.mocked(api.mappingDownload).mockResolvedValue(download)
  render(<App />); await screen.findByText('history.txt')
  const file=screen.getByText('history.txt').closest('.file-row') as HTMLElement
  expect(file).toHaveTextContent('历史输入')
  expect(within(file).queryByRole('button',{name:'提取日志类型'})).not.toBeInTheDocument()
  expect(within(file).queryByRole('button',{name:'标准字段映射'})).not.toBeInTheDocument()
  expect(api.artifactContent).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'查看产物'}))
  expect(await screen.findByText('本人历史真实值')).toBeInTheDocument()
  expect(api.artifactContent).toHaveBeenCalledExactlyOnceWith('history-enum')
  const drawer=screen.getByRole('complementary',{name:'产物详情'})
  expect(within(drawer).queryByRole('button',{name:'开始处理'})).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'关闭产物详情'}))
  fireEvent.click(screen.getByRole('button',{name:'下载产物'}))
  await waitFor(() => expect(api.mappingDownload).toHaveBeenCalledExactlyOnceWith('history-enum'))
  expect(saveDownload).toHaveBeenCalledWith(download)
})

it('ignores a prior identity clear response without changing new input or feedback',async () => {
  let reply!: (value:{id:string;actor:string;content:string}) => void
  vi.mocked(api.sendMessage).mockReturnValueOnce(new Promise(resolve => {reply=resolve}))
  render(<App />); await screen.findByRole('heading',{name:'确认任务'})
  fireEvent.click(screen.getByRole('button',{name:'清空业务数据（保留历史）'}))
  await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('c1','清空数据',expect.any(String)))
  const next={...summary,id:'c2',title:'新身份会话'}
  vi.mocked(api.selectIdentity).mockResolvedValue(other)
  vi.mocked(api.me).mockResolvedValue(other)
  vi.mocked(api.conversations).mockResolvedValue({items:[next]})
  vi.mocked(api.conversation).mockResolvedValue({...next,messages:[],files:[],runs:[]})
  fireEvent.change(screen.getByLabelText('开发身份切换'),{target:{value:'u2'}})
  await screen.findByRole('heading',{name:'新身份会话'})
  fireEvent.change(screen.getByLabelText('消息内容'),{target:{value:'新身份未发送文本'}})
  await act(async () => reply({id:'old-clear',actor:'user',content:'清空数据'}))
  expect(screen.getByLabelText('消息内容')).toHaveValue('新身份未发送文本')
  expect(screen.queryByText('清空业务数据已排队，历史结果和未发送文本会保留。')).not.toBeInTheDocument()
  expect(api.sendMessage).toHaveBeenCalledTimes(1)
})
