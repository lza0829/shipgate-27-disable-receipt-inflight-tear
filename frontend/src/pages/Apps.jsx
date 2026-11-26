import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { AppStatusBadge, DisableLamp } from '../components/FreezeBadge'

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
    setErr(''); setMsg(''); setBusy(`retire-${app.编号}`)
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

  const disable = async (app) => {
    setErr(''); setMsg(''); setBusy(`disable-${app.编号}`)
    try {
      const res = await api(`/应用/${app.编号}/停用`, {
        method: 'POST',
        body: JSON.stringify({ 备注: '应用册停用入口' }),
      })
      if (res.干净 === false || (res.缺口数 ?? 0) > 0) {
        setErr(`「${app.名称}」停用回执虽返回，但仍有 ${res.缺口数} 个缺口，不能当干净。`)
      } else {
        setMsg(`「${app.名称}」停用同核成功：停用标已落，入闸/晋升/放行写口拒绝，${res.未收口数 ?? 0} 张未收口单已收口留痕。`)
      }
      await load()
    } catch (e) {
      setErr(`停用整笔退回：${e.message}`)
      await load().catch(() => {})
    } finally {
      setBusy(null)
    }
  }

  const enable = async (app) => {
    setErr(''); setMsg(''); setBusy(`enable-${app.编号}`)
    try {
      await api(`/应用/${app.编号}`, { method: 'PATCH', body: JSON.stringify({ 状态: '启用' }) })
      setMsg(`「${app.名称}」已恢复启用，停用推进写口重开。`)
      await load()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(null)
    }
  }

  const heal = async (app) => {
    setErr(''); setMsg(''); setBusy(`heal-${app.编号}`)
    try {
      const res = await api(`/应用/${app.编号}/收口`, { method: 'POST' })
      setMsg(`「${app.名称}」${res.收口动作 || '已重放'}，缺口 ${res.缺口数 ?? 0}。`)
      await load()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="panel">
      <h2>应用名册 · 停用入口与旁读</h2>
      <p className="muted">
        停用不是只亮成功灯：停用标、入闸/晋升/放行写口拒、在途单收口痕迹与审计重放必须同命运。
        退役仍沿用“带在途退役、冻结只读”的更强命运。
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
              <th>编号</th><th>名称</th><th>负责人</th><th>状态/停用灯</th><th>开闭态</th>
              <th>未收口发版单</th><th>缺口</th><th>写口同屏</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const retired = r.状态 === '退役' || r.是否退役 === true
              const stableRetired = r.状态 === '退役'
              const suspendedFate = r.停用 === true || String(r.状态 || '').includes('停用')
              const stableDisabled = r.状态 === '停用'
              const light = r.停用核?.灯 || r.停用灯 || (suspendedFate ? 'gap' : 'off')
              const gaps = r.停用缺口数 ?? r.停用核?.缺口数 ?? 0
              return (
                <tr key={r.编号} className={`${retired ? 'row-retired' : ''} ${suspendedFate ? 'row-disabled' : ''}`.trim()} data-app-status={r.状态} data-app-fate={r.应用命运 || r.命运态 || (suspendedFate ? 'suspended' : retired ? 'retired' : 'open')}>
                  <td>{r.编号}</td>
                  <td>{r.名称}</td>
                  <td>{r.负责人}</td>
                  <td>
                    <AppStatusBadge status={r.状态} light={light} />
                    <div className="lamp-inline"><DisableLamp light={light} count={gaps} /></div>
                  </td>
                  <td data-field="开闭态">{r.开闭态}</td>
                  <td>
                    <span data-field="未收口数">{r.未收口数 ?? 0}</span>
                    {retired && (r.冻结在途数 > 0) && (
                      <span className="muted">（冻结在途 {r.冻结在途数}）</span>
                    )}
                  </td>
                  <td data-field="停用缺口数" data-gap-count={gaps}>
                    {gaps ? <span className="gap-count">{gaps} 个缺口</span> : <span className="muted">0</span>}
                  </td>
                  <td className="mouth-cell" data-field="写口同屏">
                    {['入闸', '晋升', '放行'].map((m) => {
                      const open = r.写口?.[m]
                      return (
                        <span
                          key={m}
                          className={`mouth-chip ${open ? 'chip-open' : 'chip-closed'}`}
                          data-app-mouth={m}
                          data-open={open ? '1' : '0'}
                        >
                          {m}{open ? '开' : '拒'}
                        </span>
                      )
                    })}
                  </td>
                  <td>
                    {stableRetired ? (
                      <span className="muted">已退役（终态）</span>
                    ) : (
                      <div className="action-stack">
                        {!stableDisabled && !retired && (
                          <button
                            type="button"
                            className="warn disable-btn"
                            disabled={busy === `disable-${r.编号}`}
                            onClick={() => disable(r)}
                          >
                            {busy === `disable-${r.编号}` ? '停用中…' : suspendedFate ? '停用归正' : '停用'}
                          </button>
                        )}
                        {stableDisabled && (
                          <button
                            type="button"
                            className="secondary enable-btn"
                            disabled={busy === `enable-${r.编号}`}
                            onClick={() => enable(r)}
                          >
                            启用
                          </button>
                        )}
                        <button type="button" className="secondary heal-btn" disabled={busy === `heal-${r.编号}`} onClick={() => heal(r)}>
                          重放收口
                        </button>
                        <button
                          type="button"
                          className="danger retire-btn"
                          disabled={busy === `retire-${r.编号}`}
                          onClick={() => retire(r)}
                        >
                          {busy === `retire-${r.编号}` ? '退役中…' : '退役'}
                        </button>
                      </div>
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
