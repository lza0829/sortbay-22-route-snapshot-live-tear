import React, { useState } from 'react'
import { api } from '../api'
import { useDataChanged } from '../refresh'

export default function AuditPage() {
  const [rows, setRows] = useState([])
  const [scanId, setScanId] = useState('')
  const [replay, setReplay] = useState(null)
  const [err, setErr] = useState('')

  const load = () => api('/审计').then(setRows).catch((e) => setErr(e.message))
  useDataChanged(load)

  const runReplay = async () => {
    setErr(''); setReplay(null)
    try {
      const id = Number(scanId)
      const result = await api(`/扫描/${id}/重放`)
      setReplay(result)
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="panel">
      <h2>审计与分拣线重放</h2>
      {err && <div className="err">{err}</div>}
      <div className="row">
        <label>扫描编号<input value={scanId} onChange={(e) => setScanId(e.target.value)} placeholder="例如 1" /></label>
        <button type="button" onClick={runReplay}>按选定口径重放</button>
      </div>
      {replay && (
        <div className={replay.重放一致 ? 'msg' : 'err'}>
          重放 {replay.barcode}：应落 {replay.应落口门码}，实落 {replay.实落口门码 || '未裁决'}，
          一致={replay.重放一致 ? '是' : '否'}；口径={replay.路由口径}
          <pre className="receipt">{JSON.stringify(replay.步骤, null, 2)}</pre>
        </div>
      )}
      <table>
        <thead><tr><th>编号</th><th>类型</th><th>关联</th><th>动作</th><th>时间</th><th>明细</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.id}</td><td>{r.kind}</td><td>{r.ref_id ?? '-'}</td>
              <td>{r.action}</td><td>{r.created_at}</td><td>{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
