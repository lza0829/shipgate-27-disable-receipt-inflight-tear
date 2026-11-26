import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { AppStatusBadge } from '../components/FreezeBadge'

const surface_panel = true
export default function Apps() {
  const [rows, setRows] = useState([])
  const [name, setName] = useState('')
  const [owner, setOwner] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(null)

  const load = () => api('/应用').then(setRows).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])

  const create = async () => {
    setErr(''); setMsg('')
    try {
      await api('/应用', { method: 'POST', body: JSON.stringify({ 名称: name, 负责人: owner, 状态: '启用' }) })
      setName(''); setOwner(''); load()
    } catch (e) { setErr(e.message) }
  }

  const retire = async (app) => {
    setErr(''); setMsg(''); setBusy(app.编号)
    try {
      const res = await api(`/应用/${app.编号}/退役`, {
        method: 'POST',
        body: JSON.stringify({ 备注: '应用名册点退役' }),
      })
      const n = res.未收口数 ?? 0
      setMsg(`「${app.名称}」已退役：开闭态=退役冻结，${n} 张未收口发版单全部冻结可核，各 pipeline 写口已关闭。`)
      await load()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="panel">
      <h2>应用名册</h2>
      <p className="muted">
        退役命运（全站一套）：允许带在途退役 —— 退役整笔成功，未收口发版单不删除，统一打“已冻结”标并关闭入闸 / 晋升 / 放行写口；总览露出冻结在途，审计留退役记录。
      </p>
      {err && <p className="err" role="alert">{err}</p>}
      {msg && <p className="ok" role="status">{msg}</p>}
      <div className="row">
        <label>名称<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>负责人<input value={owner} onChange={(e) => setOwner(e.target.value)} /></label>
        <button type="button" onClick={create}>新建应用</button>
        <button type="button" className="secondary" onClick={load}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>编号</th><th>名称</th><th>负责人</th><th>状态</th><th>开闭态</th>
              <th>未收口发版单</th><th>冻结标</th><th>写口</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const retired = r.状态 === '退役'
              return (
                <tr key={r.编号} className={retired ? 'row-retired' : ''} data-app-status={r.状态}>
                  <td>{r.编号}</td>
                  <td>{r.名称}</td>
                  <td>{r.负责人}</td>
                  <td><AppStatusBadge status={r.状态} /></td>
                  <td data-field="开闭态">{r.开闭态}</td>
                  <td>
                    <span data-field="未收口数">{r.未收口数 ?? 0}</span>
                    {retired && (r.冻结在途数 > 0) && (
                      <span className="muted">（冻结在途 {r.冻结在途数}）
                    </span>
                    )}
                  </td>
                  <td>{retired ? <span className="badge badge-frozen">已冻结</span> : <span className="muted">—</span>}</td>
                  <td className="mouth-cell">
                    {retired ? (
                      <span className="mouth-all-closed">入闸/晋升/放行 全关</span>
                    ) : (
                      <span className="muted">按规则开放</span>
                    )}
                  </td>
                  <td>
                    {retired ? (
                      <span className="muted">已退役（终态）</span>
                    ) : (
                      <button
                        type="button"
                        className="danger retire-btn"
                        disabled={busy === r.编号}
                        onClick={() => retire(r)}
                      >
                        {busy === r.编号 ? '退役中…' : '退役'}
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
