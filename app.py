import requests
import json
from datetime import datetime, timedelta
import sqlite3
from flask import Flask, render_template
from modelo_ia import CS2AIModel

app = Flask(__name__)
ia = CS2AIModel('cs2_newestcombinedmatches.csv')
API_KEY = "bpZbNL18EssiTVAJ2zVaBJ1JSlLa42fq0IVVE_TzkUoE_KboPSY"

def init_db():
    with sqlite3.connect('previsoes.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS previsoes (
                        match_id INTEGER PRIMARY KEY, campeonato TEXT, data_formatada TEXT,
                        time1 TEXT, time2 TEXT, logo1 TEXT, logo2 TEXT, favorito_ia TEXT,
                        prob_t1 REAL, prob_t2 REAL, vencedor_real TEXT, status TEXT)''')
        colunas_novas = [
            "ALTER TABLE previsoes ADD COLUMN tier TEXT DEFAULT 'unranked'",
            "ALTER TABLE previsoes ADD COLUMN placar_t1 INTEGER DEFAULT 0",
            "ALTER TABLE previsoes ADD COLUMN placar_t2 INTEGER DEFAULT 0",
            "ALTER TABLE previsoes ADD COLUMN detalhes_mapas TEXT DEFAULT '[]'"
        ]
        for comando in colunas_novas:
            try:
                c.execute(comando)
            except sqlite3.OperationalError:
                pass
        conn.commit()

init_db()

def atualizar_resultados():
    with sqlite3.connect('previsoes.db') as conn:
        c = conn.cursor()
        
        existentes = {row[0]: {'status': row[1], 'tier': row[2], 'detalhes': row[3]} 
                      for row in c.execute("SELECT match_id, status, IFNULL(tier, 'unranked'), IFNULL(detalhes_mapas, '[]') FROM previsoes").fetchall()}
        
        res = requests.get("https://api.pandascore.co/csgo/matches/past", headers={"Authorization": f"Bearer {API_KEY}"}, params={"per_page": 100})
        
        if res.status_code == 200:
            for jogo in res.json():
                match_id = jogo['id']
                winner_dict = jogo.get('winner')
                
                if not winner_dict or len(jogo.get('opponents', [])) < 2:
                    continue
                    
                vencedor_real = winner_dict.get('name')
                t = jogo.get('tournament', {}).get('tier')
                tier_real = str(t).lower() if t else 'unranked'
                if tier_real == 'none': tier_real = 'unranked'

                t1_id = jogo['opponents'][0]['opponent']['id']
                t2_id = jogo['opponents'][1]['opponent']['id']

                placar_t1, placar_t2 = 0, 0
                for r in jogo.get('results', []):
                    if r.get('team_id') == t1_id: placar_t1 = r.get('score', 0)
                    elif r.get('team_id') == t2_id: placar_t2 = r.get('score', 0)

                # 💡 NOVA LÓGICA DE MAPAS (Lida com a falta de Rounds na API Gratuita)
                detalhes_mapas = []
                for g in jogo.get('games', []):
                    if g.get('status') == 'finished':
                        map_obj = g.get('map')
                        mapa_nome = map_obj.get('name', f"Mapa {g.get('position')}") if map_obj else f"Mapa {g.get('position')}"
                        
                        s1, s2 = 0, 0
                        for r in g.get('results', []):
                            if r.get('team_id') == t1_id: s1 = r.get('score', 0)
                            elif r.get('team_id') == t2_id: s2 = r.get('score', 0)
                            
                        ganhador_id = g.get('winner', {}).get('id') if g.get('winner') else None
                        
                        if s1 == 0 and s2 == 0:
                            # Sem rounds, usamos VENCEU / PERDEU baseado no ganhador_id
                            res1 = "VENCEU" if ganhador_id == t1_id else ("PERDEU" if ganhador_id == t2_id else "-")
                            res2 = "VENCEU" if ganhador_id == t2_id else ("PERDEU" if ganhador_id == t1_id else "-")
                            w1 = (ganhador_id == t1_id)
                            w2 = (ganhador_id == t2_id)
                        else:
                            # Se a API enviar os Rounds, mostramos os números
                            res1, res2 = s1, s2
                            w1 = (s1 > s2)
                            w2 = (s2 > s1)

                        detalhes_mapas.append({
                            "mapa": mapa_nome, 
                            "r1": res1, 
                            "r2": res2,
                            "w1": w1,
                            "w2": w2
                        })

                detalhes_json = json.dumps(detalhes_mapas)

                if match_id in existentes:
                    status_banco = existentes[match_id]['status']
                    tier_banco = existentes[match_id]['tier']
                    detalhes_banco = existentes[match_id]['detalhes']
                    
                    precisa_atualizar = False
                    if status_banco == 'pendente': 
                        precisa_atualizar = True
                    elif tier_banco == 'unranked' and tier_real != 'unranked': 
                        precisa_atualizar = True
                    elif detalhes_banco == '[]' and detalhes_json != '[]': 
                        precisa_atualizar = True
                    # 💡 AUTO-CURA: Se o banco tiver os zeros falsos do passado, ele regravará!
                    elif '"s1": 0, "s2": 0' in detalhes_banco:
                        precisa_atualizar = True
                    
                    if precisa_atualizar:
                        c.execute("UPDATE previsoes SET vencedor_real=?, status='finalizado', tier=?, placar_t1=?, placar_t2=?, detalhes_mapas=? WHERE match_id=?", 
                                  (vencedor_real, tier_real, placar_t1, placar_t2, detalhes_json, match_id))
                else:
                    t1_dict = jogo['opponents'][0]['opponent']
                    t2_dict = jogo['opponents'][1]['opponent']
                    time1, time2 = t1_dict.get('name'), t2_dict.get('name')
                    st1, st2 = ia.buscar_estatisticas(time1), ia.buscar_estatisticas(time2)
                    
                    if st1 and st2:
                        p1, p2 = ia.prever(st1, st2)
                        favorito = time1 if p1 > p2 else time2
                        campeonato = jogo.get('league', {}).get('name', 'Campeonato Oficial')
                        dt_obj = datetime.strptime(jogo['begin_at'], "%Y-%m-%dT%H:%M:%SZ") - timedelta(hours=3) if jogo.get('begin_at') else datetime.now()
                        data_formatada = dt_obj.strftime("%d/%m/%Y às %H:%M")
                        logo1 = t1_dict.get('image_url') or "https://cdn-icons-png.flaticon.com/512/4333/4333609.png"
                        logo2 = t2_dict.get('image_url') or "https://cdn-icons-png.flaticon.com/512/4333/4333609.png"
                        
                        c.execute('''INSERT INTO previsoes 
                            (match_id, campeonato, data_formatada, time1, time2, logo1, logo2, favorito_ia, prob_t1, prob_t2, vencedor_real, status, tier, placar_t1, placar_t2, detalhes_mapas) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'finalizado', ?, ?, ?, ?)''', 
                            (match_id, campeonato, data_formatada, time1, time2, logo1, logo2, favorito, p1, p2, vencedor_real, tier_real, placar_t1, placar_t2, detalhes_json))
            conn.commit()

def processar_jogos(jogos_brutos, page_type):
    matches, datas_unicas = [], set()
    for jogo in jogos_brutos:
        if len(jogo.get('opponents', [])) < 2: continue
        
        t1_dict = jogo['opponents'][0]['opponent']
        t2_dict = jogo['opponents'][1]['opponent']
        dt_obj = datetime.strptime(jogo['begin_at'], "%Y-%m-%dT%H:%M:%SZ") - timedelta(hours=3) if jogo.get('begin_at') else datetime.now()
        data_apenas = dt_obj.strftime("%d/%m/%Y")
        datas_unicas.add(data_apenas)
        
        t = jogo.get('tournament', {}).get('tier')
        tier_limpo = str(t).lower() if t else 'unranked'
        if tier_limpo == 'none': tier_limpo = 'unranked'
        
        match = {
            'id': jogo['id'], 'campeonato': jogo.get('league', {}).get('name', 'Campeonato Oficial'),
            'tier': tier_limpo, 'data_formatada': dt_obj.strftime("%d/%m/%Y às %H:%M"),
            'data_apenas': data_apenas, 'time1': t1_dict.get('name'), 'time2': t2_dict.get('name'),
            'logo1': t1_dict.get('image_url') or "https://cdn-icons-png.flaticon.com/512/4333/4333609.png",
            'logo2': t2_dict.get('image_url') or "https://cdn-icons-png.flaticon.com/512/4333/4333609.png",
            'tem_dados': False
        }
        
        st1, st2 = ia.buscar_estatisticas(match['time1']), ia.buscar_estatisticas(match['time2'])
        
        if st1 and st2:
            match['tem_dados'] = True
            p1, p2 = ia.prever(st1, st2)
            match['prob_t1'], match['prob_t2'] = p1, p2
            match['favorito'] = match['time1'] if p1 > p2 else match['time2']
            match['cor_t1'] = "#3b82f6" if p1 > p2 else "#475569"
            match['cor_t2'] = "#475569" if p1 > p2 else "#3b82f6"
            
            match['rx_rat1'], match['rx_rat2'] = f"{st1['rating']:.2f}", f"{st2['rating']:.2f}"
            match['rx_win1'] = f"{st1['winrate']*100:.1f}%" if st1['winrate'] <= 1 else f"{st1['winrate']:.1f}%"
            match['rx_win2'] = f"{st2['winrate']*100:.1f}%" if st2['winrate'] <= 1 else f"{st2['winrate']:.1f}%"
            match['rx_lan1'] = f"{st1['lan_winrate']*100:.1f}%" if st1['lan_winrate'] <= 1 else f"{st1['lan_winrate']:.1f}%"
            match['rx_lan2'] = f"{st2['lan_winrate']*100:.1f}%" if st2['lan_winrate'] <= 1 else f"{st2['lan_winrate']:.1f}%"
            match['hw_rat'] = 1 if st1['rating'] > st2['rating'] else 2
            match['hw_win'] = 1 if st1['winrate'] > st2['winrate'] else 2
            match['hw_lan'] = 1 if st1['lan_winrate'] > st2['lan_winrate'] else 2

            if page_type == 'futuro':
                with sqlite3.connect('previsoes.db') as conn:
                    conn.cursor().execute('''INSERT OR IGNORE INTO previsoes 
                        (match_id, campeonato, data_formatada, time1, time2, logo1, logo2, favorito_ia, prob_t1, prob_t2, status, tier) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendente', ?)''', 
                        (match['id'], match['campeonato'], match['data_formatada'], match['time1'], match['time2'], match['logo1'], match['logo2'], match['favorito'], p1, p2, match['tier']))
                    conn.commit()

        if page_type == 'aovivo':
            s1, s2 = 0, 0
            for r in jogo.get('results', []):
                if r.get('team_id') == t1_dict.get('id'): s1 = r.get('score', 0)
                elif r.get('team_id') == t2_dict.get('id'): s2 = r.get('score', 0)
            match['map_score1'], match['map_score2'] = s1, s2
            
            r1, r2 = "-", "-"
            for game in jogo.get('games', []):
                if game.get('status') == 'running':
                    for r in game.get('results', []):
                        if r.get('team_id') == t1_dict.get('id'): r1 = r.get('score', 0)
                        elif r.get('team_id') == t2_dict.get('id'): r2 = r.get('score', 0)
                    break
            match['round_score1'], match['round_score2'] = r1, r2
            
        matches.append(match)
        
    return matches, sorted(list(datas_unicas))

@app.route('/')
def index():
    res = requests.get("https://api.pandascore.co/csgo/matches/upcoming", headers={"Authorization": f"Bearer {API_KEY}"}, params={"filter[videogame_title]": "cs-2", "per_page": 100, "sort": "begin_at"})
    matches, datas = processar_jogos(res.json() if res.status_code == 200 else [], 'futuro')
    return render_template('painel.html', page='futuro', matches=matches, datas=datas, acuracia=ia.acuracia, total=ia.total_partidas)

@app.route('/aovivo')
def aovivo():
    res = requests.get("https://api.pandascore.co/csgo/matches/running", headers={"Authorization": f"Bearer {API_KEY}"}, params={"filter[videogame_title]": "cs-2"})
    matches, _ = processar_jogos(res.json() if res.status_code == 200 else [], 'aovivo')
    return render_template('painel.html', page='aovivo', matches=matches, acuracia=ia.acuracia, total=ia.total_partidas)

@app.route('/resultados')
def resultados():
    atualizar_resultados()
    with sqlite3.connect('previsoes.db') as conn:
        rows = conn.cursor().execute("SELECT match_id, campeonato, data_formatada, time1, time2, logo1, logo2, favorito_ia, prob_t1, prob_t2, vencedor_real, IFNULL(tier, 'unranked'), IFNULL(placar_t1, 0), IFNULL(placar_t2, 0), IFNULL(detalhes_mapas, '[]') FROM previsoes WHERE status='finalizado' ORDER BY match_id DESC").fetchall()
    
    matches, datas_unicas = [], set()
    for r in rows:
        tier_limpo = 'unranked' if not r[11] or r[11] == 'none' else r[11]
        
        m = {'id': r[0], 'campeonato': r[1], 'data_formatada': r[2], 'time1': r[3], 'time2': r[4], 'logo1': r[5], 'logo2': r[6], 'favorito': r[7], 'prob_t1': r[8], 'prob_t2': r[9], 'vencedor_real': r[10], 'tier': tier_limpo, 'placar_t1': r[12], 'placar_t2': r[13]}
        
        try:
            m['mapas'] = json.loads(r[14])
        except:
            m['mapas'] = []

        m['data_apenas'] = m['data_formatada'].split(' ')[0]
        datas_unicas.add(m['data_apenas'])
        
        m['cor_t1'] = "#3b82f6" if m['prob_t1'] > m['prob_t2'] else "#475569"
        m['cor_t2'] = "#475569" if m['prob_t1'] > m['prob_t2'] else "#3b82f6"
        m['acertou'] = (m['favorito'] == m['vencedor_real'])
        matches.append(m)
        
    return render_template('painel.html', page='resultados', matches=matches, datas=sorted(list(datas_unicas)), acuracia=ia.acuracia, total=ia.total_partidas)

if __name__ == '__main__':
    print("🚀 Servidor Flask Iniciado! Acesse http://127.0.0.1:5000")
    app.run(debug=True, port=5000)