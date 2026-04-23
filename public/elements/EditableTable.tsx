/**
 * 可编辑表格组件 - EditableTable
 * 
 * 用于Chainlit CustomElement
 * 支持排序、筛选、编辑功能
 */

import React, { useState, useMemo } from 'react'

interface MappingItem {
  原始字段名: string
  系统属性名称: string
  匹配状态: string
}

interface EditableTableProps {
  data: MappingItem[]
  onSubmit?: (data: MappingItem[]) => void
}

export default function EditableTable({ data, onSubmit }: EditableTableProps) {
  const [rows, setRows] = useState<MappingItem[]>(data)
  const [sortConfig, setSortConfig] = useState<{ key: keyof MappingItem; direction: 'asc' | 'desc' } | null>(null)
  const [filterText, setFilterText] = useState('')
  const [editingCell, setEditingCell] = useState<{ row: number; key: keyof MappingItem } | null>(null)

  // 排序和筛选
  const processedData = useMemo(() => {
    let result = [...rows]
    
    // 筛选
    if (filterText) {
      const lowerFilter = filterText.toLowerCase()
      result = result.filter(row => 
        Object.values(row).some(val => 
          String(val).toLowerCase().includes(lowerFilter)
        )
      )
    }
    
    // 排序
    if (sortConfig) {
      result.sort((a, b) => {
        const aVal = String(a[sortConfig.key])
        const bVal = String(b[sortConfig.key])
        if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1
        if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1
        return 0
      })
    }
    
    return result
  }, [rows, sortConfig, filterText])

  // 排序处理
  const handleSort = (key: keyof MappingItem) => {
    setSortConfig(prev => ({
      key,
      direction: prev?.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
    }))
  }

  // 编辑单元格
  const handleCellClick = (rowIndex: number, key: keyof MappingItem) => {
    // 只允许编辑"系统属性名称"列
    if (key === '系统属性名称') {
      setEditingCell({ row: rowIndex, key })
    }
  }

  // 处理编辑输入
  const handleEditChange = (value: string) => {
    if (editingCell) {
      const newRows = [...rows]
      newRows[editingCell.row][editingCell.key] = value
      setRows(newRows)
    }
  }

  // 完成编辑
  const handleEditBlur = () => {
    setEditingCell(null)
  }

  // 提交数据
  const handleSubmit = () => {
    if (onSubmit) {
      onSubmit(rows)
    } else {
      // 使用console.log输出到后端日志
      console.log('[EditableTable] Updated data:', JSON.stringify(rows, null, 2))
      alert('数据已更新！请查看控制台输出。')
    }
  }

  // 导出Excel
  const handleExport = () => {
    const headers: (keyof MappingItem)[] = ['原始字段名', '系统属性名称', '匹配状态']
    const csvContent = [
      headers.join(','),
      ...rows.map(row => headers.map(h => `"${row[h]}"`).join(','))
    ].join('\n')
    
    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `字段映射表_${new Date().toISOString().slice(0,10)}.csv`
    link.click()
  }

  // 统计
  const stats = useMemo(() => {
    const total = rows.length
    const matched = rows.filter(r => r.匹配状态 === '匹配成功').length
    const unmatched = total - matched
    return { total, matched, unmatched }
  }, [rows])

  return (
    <div style={{ padding: '20px', fontFamily: 'Arial, sans-serif' }}>
      {/* 统计信息 */}
      <div style={{ 
        display: 'flex', 
        gap: '20px', 
        marginBottom: '16px',
        padding: '12px',
        backgroundColor: '#f5f5f5',
        borderRadius: '8px'
      }}>
        <div><strong>总字段数：</strong>{stats.total}</div>
        <div style={{ color: 'green' }}><strong>匹配成功：</strong>{stats.matched}</div>
        <div style={{ color: '#e74c3c' }}><strong>未匹配：</strong>{stats.unmatched}</div>
      </div>

      {/* 操作栏 */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
        <input
          type="text"
          placeholder="🔍 搜索..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          style={{
            padding: '8px 12px',
            border: '1px solid #ddd',
            borderRadius: '4px',
            width: '200px'
          }}
        />
        <button
          onClick={handleSubmit}
          style={{
            padding: '8px 16px',
            backgroundColor: '#27ae60',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          ✅ 确认修改
        </button>
        <button
          onClick={handleExport}
          style={{
            padding: '8px 16px',
            backgroundColor: '#3498db',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          📥 导出CSV
        </button>
      </div>

      {/* 表格 */}
      <div style={{ overflowX: 'auto', border: '1px solid #ddd', borderRadius: '8px' }}>
        <table style={{ 
          width: '100%', 
          borderCollapse: 'collapse',
          fontSize: '14px'
        }}>
          <thead>
            <tr style={{ backgroundColor: '#f8f9fa' }}>
              {(['原始字段名', '系统属性名称', '匹配状态'] as const).map(header => (
                <th
                  key={header}
                  onClick={() => header !== '匹配状态' && handleSort(header)}
                  style={{
                    padding: '12px',
                    textAlign: 'left',
                    borderBottom: '2px solid #dee2e6',
                    cursor: header !== '匹配状态' ? 'pointer' : 'default',
                    userSelect: 'none'
                  }}
                >
                  {header} {sortConfig?.key === header && (sortConfig.direction === 'asc' ? '↑' : '↓')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {processedData.map((row, index) => (
              <tr 
                key={index}
                style={{ 
                  backgroundColor: row.匹配状态 === '未匹配' ? '#fff5f5' : 'white',
                  borderBottom: '1px solid #eee'
                }}
              >
                <td style={{ padding: '10px' }}>{row.原始字段名}</td>
                <td
                  onClick={() => handleCellClick(index, '系统属性名称')}
                  style={{
                    padding: '10px',
                    cursor: 'pointer',
                    backgroundColor: editingCell?.row === index && editingCell?.key === '系统属性名称' ? '#e8f4fd' : 'transparent',
                    outline: editingCell?.row === index && editingCell?.key === '系统属性名称' ? '2px solid #3498db' : 'none'
                  }}
                >
                  {editingCell?.row === index && editingCell?.key === '系统属性名称' ? (
                    <input
                      type="text"
                      value={row.系统属性名称}
                      onChange={(e) => handleEditChange(e.target.value)}
                      onBlur={handleEditBlur}
                      autoFocus
                      style={{
                        width: '100%',
                        padding: '4px',
                        border: '1px solid #3498db',
                        borderRadius: '4px'
                      }}
                    />
                  ) : (
                    row.系统属性名称
                  )}
                </td>
                <td style={{ 
                  padding: '10px',
                  color: row.匹配状态 === '匹配成功' ? 'green' : '#e74c3c'
                }}>
                  {row.匹配状态}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 提示信息 */}
      <div style={{ 
        marginTop: '12px', 
        color: '#666', 
        fontSize: '12px' 
      }}>
        💡 提示：点击"系统属性名称"列的单元格可以直接编辑，编辑完成后点击"确认修改"保存。
      </div>
    </div>
  )
}