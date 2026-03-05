import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

class CS2AIModel:
    def __init__(self, caminho_csv):
        print("🤖 A iniciar o Treinamento Avançado da IA...")
        self.df = pd.read_csv(caminho_csv)
        self.features = [
            'rating_diff', 'kpr_diff', 'dpr_diff', 
            'team1_overall_winrate', 'team2_overall_winrate',
            'team1_lan_winrate', 'team2_lan_winrate',
            'team1_online_winrate', 'team2_online_winrate',
            'star_player_advantage', 'consistency_advantage'
        ]
        self.df_limpo = self.df.dropna(subset=self.features + ['winner', 'team1_name', 'team2_name'])
        self.model = None
        self.acuracia = 0
        self.total_partidas = 0
        self._treinar()

    def _treinar(self):
        X = self.df_limpo[self.features]
        y = (self.df_limpo['winner'] == 'team1').astype(int)
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        self.model = RandomForestClassifier(n_estimators=200, random_state=42, max_depth=15)
        self.model.fit(X_train, y_train)
        
        previsoes_teste = self.model.predict(X_test)
        self.acuracia = round(accuracy_score(y_test, previsoes_teste) * 100, 1)
        self.total_partidas = len(X)
        print(f"✅ Modelo Pronto! Acurácia validada: {self.acuracia}%")

    def buscar_estatisticas(self, nome_time):
        nome_busca = nome_time.lower().strip()
        apelidos = {
            "nip": "ninjas in pyjamas", "g2 esports": "g2", "navi": "natus vincere", 
            "faze clan": "faze", "team vitality": "vitality", "team spirit": "spirit", 
            "team liquid": "liquid", "vp": "virtus.pro", "mouz": "mousesports"
        }
        if nome_busca in apelidos:
            nome_busca = apelidos[nome_busca]

        recente = self.df_limpo[self.df_limpo['team1_name'].str.lower() == nome_busca]
        if recente.empty:
            recente = self.df_limpo[self.df_limpo['team1_name'].str.lower().str.contains(nome_busca, regex=False)]

        if not recente.empty:
            ultima = recente.iloc[-1]
            return {
                'rating': ultima['team1_avg_RATING'], 'kpr': ultima['team1_avg_KPR'],
                'dpr': ultima['team1_avg_DPR'], 'winrate': ultima['team1_overall_winrate'],
                'lan_winrate': ultima['team1_lan_winrate'], 'online_winrate': ultima['team1_online_winrate'],
                'top_player': ultima['team1_top_player'], 'consistency': ultima['team1_rating_std']
            }
        return None

    def prever(self, st1, st2):
        cenario = pd.DataFrame([{
            'rating_diff': st1['rating'] - st2['rating'], 'kpr_diff': st1['kpr'] - st2['kpr'],
            'dpr_diff': st1['dpr'] - st2['dpr'], 'team1_overall_winrate': st1['winrate'],
            'team2_overall_winrate': st2['winrate'], 'team1_lan_winrate': st1['lan_winrate'],
            'team2_lan_winrate': st2['lan_winrate'], 'team1_online_winrate': st1['online_winrate'],
            'team2_online_winrate': st2['online_winrate'], 'star_player_advantage': st1['top_player'] - st2['top_player'],
            'consistency_advantage': st2['consistency'] - st1['consistency']
        }])
        probs = self.model.predict_proba(cenario)[0]
        return round(probs[1] * 100, 1), round(probs[0] * 100, 1)