import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { FrozenBadge, LockedButton, isFrozen } from '../components/FreezeBadge'

// 放行页：聚焦“放行到产”这一写口。与晋升页共用同一套冻结标 / 锁定形态与后端命运。
export default function ReleaseGate() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busyId, setBusyId] = useState(null)

  const load = async () => {
    const all = await api('/发版单')
    // 可放行：已入闸 / 晋升中（逐级到产由后端裁决），以及已放行留痕行。
    setRows(all.filter((r) => ['已入闸', '晋升中', '已放行'].includes(r.状态)))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  const release = async (row) => {
    setErr(''); setMsg(''); setBusyId(row.编号)
    try {
      const updated = await api(`/发版单/${row.编号}/放行`, { method: 'POST', body: JSON.stringify({}) })
      setMsg(`放行写口回执：${updated.发版单号} → ${updated.状态}/${updated.当前环境 || ''}`)
      await load()
    } catch (e) {
      setErr(`放行被驳回（写口关闭）：${e.message}`)
      await load()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="panel">
      <h2>放行页 · 生产放行写口</h2>
      <p className="muted">
        退役命运下，应用一旦退役，其未收口单在此页显示“已冻结”，放行按钮保留为点按探针但一定被后端驳回，单子不会被推到产，也不会从列表消失。
      </p>
      {err && <p className="err" role="alert">{err}</p>}
      {msg && <p className="ok" role="status">{msg}</p>}
      <div className="row">
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th>
              <th>冻结标</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const frozen = isFrozen(r)
              const released = r.状态 === '已放行'
              return (
                <tr key={r.编号} className={frozen ? 'row-frozen' : ''} data-frozen={frozen ? '1' : '0'}>
                  <td>{r.发版单号}</td>
                  <td>{r.应用}</td>
                  <td>{r.目标版本}</td>
                  <td>{r.状态}</td>
                  <td>{r.当前环境 || '-'}</td>
                  <td><FrozenBadge row={r} /></td>
                  <td>
                    {released ? (
                      <span className="muted">已放行到{r.当前环境 || '产'}</span>
                    ) : (
                      <LockedButton
                        frozen={frozen}
                        className="danger release-row-btn"
                        onClick={() => release(r)}
                      >
                        {busyId === r.编号 ? '放行中…' : frozen ? '放行（已冻结·探针）' : '放行到产'}
                      </LockedButton>
                    )}
                  </td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={7} className="muted">暂无可放行发版单</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
