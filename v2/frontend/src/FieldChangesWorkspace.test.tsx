import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FieldChangesWorkspace } from './FieldChangesWorkspace'
import { api, type FieldChangePreview } from './api'
vi.mock('./api')
const preview: FieldChangePreview = {run_id:'source', task_id:'task', revision:1, status:'ready', current:true, apply_run_id:null, applied_artifact_id:null, undo_run_id:null, restored_artifact_id:null, selected_group_ids:['g1','g2'], groups:[
  {id:'g1',fields:['地址'],deletes:[],status:'selected',changes:[{sub_rule_id:'r1',sub_rule_name:'网络',field:'地址',kind:'add',before:null,after:{index:'地址'}}]},
  {id:'g2',fields:['旧字段'],deletes:['旧字段'],status:'selected',changes:[{sub_rule_id:'r2',sub_rule_name:'登录',field:'旧字段',kind:'delete',before:{index:'旧字段'},after:null}]},
]}
const props = {summary:preview, editable:true,onBack:vi.fn(),onRefresh:vi.fn(async()=>{}),onExecution:vi.fn()}
beforeEach(()=>{
 vi.mocked(api.fieldPreview).mockResolvedValue(structuredClone(preview))
 vi.mocked(api.applyFields).mockResolvedValue({run:{id:'applied',status:'queued'}})
 vi.mocked(api.run).mockResolvedValue({id:'applied',status:'succeeded'})
 vi.mocked(api.confirmFieldDeletion).mockResolvedValue({token:'bound-token',checkpoint_revision:1,payload:{deletes:['旧字段'],downstream:[{id:'export',kind:'config_export',version:2}]}})
 vi.mocked(api.selectFields).mockResolvedValue({...preview,revision:2,selected_group_ids:['g1']})
 vi.mocked(api.undoFields).mockResolvedValue({run:{id:'undo',status:'queued'}})
 vi.mocked(api.cancelFields).mockResolvedValue({})
})
afterEach(()=>{cleanup();vi.resetAllMocks()})
it('preserves atomic selection across rule tabs with keyboard navigation',async()=>{
 render(<FieldChangesWorkspace {...props}/>);await screen.findByRole('checkbox',{name:'地址'})
 expect(screen.getByText('添加：地址').closest('.field-change')).toHaveClass('field-add')
 expect(screen.getByText('已选择', {selector: '.status-text span'}).closest('.status-text')).toHaveClass('tone-info')
 const login=screen.getByRole('tab',{name:'登录'});fireEvent.keyDown(screen.getByRole('tab',{name:'网络'}),{key:'ArrowRight'})
 expect(login).toHaveFocus();expect(login).toHaveAttribute('aria-selected','true')
 fireEvent.click(screen.getByRole('checkbox',{name:'旧字段'}))
 await waitFor(()=>expect(api.selectFields).toHaveBeenCalledWith('source',1,['g1'],expect.any(String)))
 await waitFor(()=>expect(screen.getByRole('checkbox',{name:'旧字段'})).not.toBeChecked())
 fireEvent.click(screen.getByRole('button',{name:'应用所选变更并继续'}))
 await waitFor(()=>expect(api.applyFields).toHaveBeenCalledWith('source',2,expect.any(String),undefined))
 expect(api.confirmFieldDeletion).not.toHaveBeenCalled();await waitFor(()=>expect(props.onBack).toHaveBeenCalled())
})
it('shows one combined deletion confirmation and returns only after success',async()=>{
 render(<FieldChangesWorkspace {...props}/>);await screen.findByText('添加：地址')
 fireEvent.click(screen.getByRole('button',{name:'应用所选变更并继续'}))
 const dialog=await screen.findByRole('dialog',{name:'确认删除字段'})
 expect(within(dialog).getByText(/版本/)).toBeInTheDocument();expect(api.applyFields).not.toHaveBeenCalled()
 fireEvent.click(within(dialog).getByRole('button',{name:'确认删除并应用'}))
 await waitFor(()=>expect(api.applyFields).toHaveBeenCalledWith('source',1,expect.any(String),'bound-token'))
 await waitFor(()=>expect(props.onBack).toHaveBeenCalled());expect(api.confirmFieldDeletion).toHaveBeenCalledTimes(1)
})
it('keeps failure visible and reuses the apply receipt on retry',async()=>{
 vi.mocked(api.fieldPreview).mockResolvedValue({...preview,selected_group_ids:['g1']})
 vi.mocked(api.applyFields).mockRejectedValueOnce(new Error('网络暂不可用'))
 render(<FieldChangesWorkspace {...props}/>);await screen.findByText('添加：地址')
 fireEvent.click(screen.getByRole('button',{name:'应用所选变更并继续'}));await screen.findByText('网络暂不可用')
 expect(props.onBack).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'应用所选变更并继续'}))
 await waitFor(()=>expect(api.applyFields).toHaveBeenCalledTimes(2))
 expect(vi.mocked(api.applyFields).mock.calls[0][2]).toBe(vi.mocked(api.applyFields).mock.calls[1][2])
})
it('restores an entire version through a new undo run',async()=>{
 const applied={...preview,status:'applied',current:false,applied_artifact_id:'artifact'}
 vi.mocked(api.fieldPreview).mockResolvedValue(applied)
 render(<FieldChangesWorkspace {...props} summary={applied}/>);fireEvent.click(await screen.findByRole('button',{name:'撤销本次变更'}))
 await waitFor(()=>expect(api.undoFields).toHaveBeenCalledWith('artifact',expect.any(String)))
 await waitFor(()=>expect(props.onRefresh).toHaveBeenCalled())
})
it('permits cancel of stale preview while blocking apply',async()=>{
 vi.mocked(api.fieldPreview).mockResolvedValue({...preview,current:false})
 render(<FieldChangesWorkspace {...props}/>);await screen.findByText(/输入或配置已变化/)
 expect(screen.queryByRole('button',{name:'应用所选变更并继续'})).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'取消本次变更'}))
 await waitFor(()=>expect(api.cancelFields).toHaveBeenCalledWith('source',1,expect.any(String)))
})
it('ignores a late preview response after leaving the workspace',async()=>{
 let resolve!:(value:FieldChangePreview)=>void
 vi.mocked(api.fieldPreview).mockReturnValue(new Promise(done=>{resolve=done}))
 const rendered=render(<FieldChangesWorkspace {...props}/>);rendered.unmount();resolve(preview)
 await Promise.resolve();expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
})
it('shows owner content in read-only mode without write controls',async()=>{
 render(<FieldChangesWorkspace {...props} editable={false}/>);await screen.findByText('添加：地址')
 expect(screen.getByRole('checkbox',{name:'地址'})).toBeDisabled()
 expect(screen.queryByRole('button',{name:'应用所选变更并继续'})).not.toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'取消本次变更'})).not.toBeInTheDocument()
})
it('rejects a late preview GET from an earlier summary revision',async()=>{
 let old!:(value:FieldChangePreview)=>void
 vi.mocked(api.fieldPreview).mockReturnValueOnce(new Promise(done=>{old=done})).mockResolvedValueOnce({...preview,revision:3,status:'applied',applied_artifact_id:'new'})
 const rendered=render(<FieldChangesWorkspace {...props}/>);
 rendered.rerender(<FieldChangesWorkspace {...props} summary={{...preview,revision:3,status:'applied'}}/>);
 await screen.findByRole('button',{name:'撤销本次变更'});old(preview)
 await waitFor(()=>expect(screen.queryByRole('button',{name:'应用所选变更并继续'})).not.toBeInTheDocument())
})
it('rejects a late selection response after a newer preview revision',async()=>{
 let saved!:(value:FieldChangePreview)=>void
 vi.mocked(api.selectFields).mockReturnValueOnce(new Promise(done=>{saved=done}))
 const rendered=render(<FieldChangesWorkspace {...props}/>);await screen.findByRole('checkbox',{name:'地址'})
 fireEvent.click(screen.getByRole('checkbox',{name:'地址'}))
 vi.mocked(api.fieldPreview).mockResolvedValueOnce({...preview,revision:3,status:'applied',applied_artifact_id:'new'})
 rendered.rerender(<FieldChangesWorkspace {...props} summary={{...preview,revision:3,status:'applied'}}/>);
 await screen.findByRole('button',{name:'撤销本次变更'});saved({...preview,revision:2,selected_group_ids:['g2']})
 await waitFor(()=>expect(screen.queryByRole('button',{name:'应用所选变更并继续'})).not.toBeInTheDocument())
})
