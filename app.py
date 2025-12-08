import streamlit as st
import pandas as pd
from urllib.parse import quote
from datetime import date, timedelta 
import datetime 
import io

# --- Configurações da Aplicação ---
st.set_page_config(layout="wide", page_title="Processador de Clientes de Aceleração V3 (Relatório Detalhado)")

st.title("🎯 Qualificação para Aceleração de Repetição (Relatório Detalhado)")
st.markdown("Filtra clientes que tiveram a **ÚLTIMA COMPRA ENVIADA** há **exatamente 28 dias** E tiveram **interação posterior** de alta intenção. O relatório exibe **TODAS as linhas** de pedido desses clientes.")

# --- Definição das Colunas ---
COL_ID = 'Codigo Cliente'
COL_NAME = 'Cliente'
COL_PHONE = 'Fone Fixo'
COL_STATUS = 'Status' 
COL_ORDER_ID = 'N. Pedido' 
COL_DATE = 'Data' 
COL_TOTAL_VALUE = 'Valor Total' 
COL_DETENTO = 'Ultimo Detento Cadastrado' 

# Colunas de SAÍDA
COL_OUT_NAME = 'Cliente_Formatado'
COL_OUT_MSG = 'Mensagem_Personalizada'

# --- Lógica de Gênero ---
FEMININE_NAMES = {
    'maria', 'ana', 'paula', 'carla', 'patricia', 'gabriela', 'juliana', 
    'fernanda', 'aline', 'bruna', 'camila', 'leticia', 'isabela', 'sofia', 
    'beatriz', 'vitoria', 'claudia', 'elena', 'raquel', 'sandra', 'valeria',
    'marcia', 'monica', 'larissa', 'eduarda', 'helena', 'regina', 'viviane', 'luciana'
}

def get_gender_parts(first_name):
    """Retorna o pronome, preposição e artigo definido com base no primeiro nome."""
    lower_name = first_name.lower()
    
    if lower_name in FEMININE_NAMES or (lower_name.endswith('a') and len(lower_name) > 2):
        return {'pronome': 'ela', 'preposicao': 'da', 'article': 'a'}
    
    return {'pronome': 'ele', 'preposicao': 'do', 'article': 'o'}


# --- Função de Lógica de Negócio (O Cérebro) ---

@st.cache_data
def process_data_aceleracao_v2(df_input):
    """
    Filtra clientes que tiveram a ÚLTIMA COMPRA ENVIADA há EXATAMENTE 28 dias 
    E que possuem NOVA atividade de alta intenção após essa data.
    Retorna o DataFrame completo (todas as linhas) para os IDs qualificados.
    """
    df_original = df_input.copy() 
    
    # 1. Checagem de colunas obrigatórias
    required_cols = [COL_ID, COL_NAME, COL_PHONE, COL_STATUS, COL_ORDER_ID, COL_DATE, COL_TOTAL_VALUE, COL_DETENTO]
    if not all(col in df_original.columns for col in required_cols):
        missing = [col for col in required_cols if col not in df_original.columns]
        raise ValueError(f"O arquivo está faltando as seguintes colunas obrigatórias: {', '.join(missing)}. Verifique '{COL_DETENTO}'.")

    metrics = {
        'original_count': len(df_original),
        'removidos_cancelados': 0,
        'coorte_28_dias_sent': 0,
        'clientes_qualificados': 0
    }
    
    # 2. Conversão da Data
    try:
        df_original[COL_DATE] = pd.to_datetime(df_original[COL_DATE], errors='coerce', dayfirst=True).dt.normalize()
    except Exception as e:
        raise ValueError(f"Erro ao converter a coluna '{COL_DATE}' para data. Erro: {e}")
    
    df_original.dropna(subset=[COL_DATE], inplace=True)
    
    # --- ETAPA 1: FILTRO DE EXCLUSÃO (CANCELAMENTO) ---
    df = df_original.copy()
    cancelados_ids = df[df[COL_STATUS].astype(str).str.lower() == 'cancelado'][COL_ID].unique()
    df = df[~df[COL_ID].isin(cancelados_ids)].copy()
    metrics['removidos_cancelados'] = metrics['original_count'] - len(df)
    
    if df.empty:
        return pd.DataFrame(), metrics 
    
    # --- ETAPA 2: IDENTIFICAÇÃO DA COORTE BASE (Filtro 1: ÚLTIMO ENVIADO há 28 dias) ---
    today = date.today() 
    date_28_days_ago = today - timedelta(days=28)
    
    # A. Encontra a ÚLTIMA DATA de pedido 'Enviado' para cada cliente
    df_enviados = df[df[COL_STATUS].astype(str).str.lower() == 'enviado'].copy()
    
    if df_enviados.empty:
        return pd.DataFrame(), metrics

    df_last_sent = df_enviados.groupby(COL_ID)[COL_DATE].max().reset_index()
    df_last_sent.rename(columns={COL_DATE: 'Ultima_Compra_Enviada'}, inplace=True)

    # B. Filtra: A última compra 'Enviada' DEVE ser de EXATAMENTE 28 dias atrás.
    coorte_28_dias_ids = df_last_sent[
        df_last_sent['Ultima_Compra_Enviada'].dt.date == date_28_days_ago
    ][COL_ID].unique()
    
    metrics['coorte_28_dias_sent'] = len(coorte_28_dias_ids)
    
    if len(coorte_28_dias_ids) == 0:
        return pd.DataFrame(), metrics

    # C. Reduzimos o DataFrame para clientes na coorte (em todas as suas atividades)
    df_candidatos = df[df[COL_ID].isin(coorte_28_dias_ids)].copy()
    
    # D. Merge para obter a data de referência 'Enviado' na mesma linha
    df_candidatos = df_candidatos.merge(df_last_sent, on=COL_ID, how='left')


    # --- ETAPA 3: FILTRO DE INTENÇÃO POSTERIOR (Filtro 2: Interação mais recente que a Compra Enviada) ---
    
    # A. Define os status que indicam nova intenção
    status_nova_intencao = ['aguardando pagamento', 'pedido salvo', 'pagamento efetuado'] 
    
    # B. Identifica quais pedidos DESSES clientes são MAIS RECENTES que a última compra enviada (28 dias atrás)
    df_interacao_posterior = df_candidatos[
        (df_candidatos[COL_DATE] > df_candidatos['Ultima_Compra_Enviada']) &
        (df_candidatos[COL_STATUS].astype(str).str.lower().isin(status_nova_intencao))
    ].copy()

    # C. IDs Finais: Clientes que tiveram uma compra enviada 28 dias atrás E tiveram atividade nova
    clientes_aceleracao_ids = df_interacao_posterior[COL_ID].unique()

    # --- ETAPA 4: Geração do DataFrame FINAL DE SAÍDA (TODAS AS LINHAS PARA OS IDs QUALIFICADOS) ---
    
    # A. Filtra o DataFrame de Candidatos (df_candidatos) para incluir APENAS os IDs que passaram no Filtro 2
    df_full_output = df_candidatos[df_candidatos[COL_ID].isin(clientes_aceleracao_ids)].copy()

    # B. GERAÇÃO DA MENSAGEM (USANDO O PEDIDO DE REFERÊNCIA DE 28 DIAS)
    
    # 1. Pegamos a linha do pedido ENVIADO (de 28 dias atrás) para usar na mensagem
    df_reference = df_enviados[df_enviados[COL_ID].isin(clientes_aceleracao_ids)].copy()
    df_reference = df_reference.merge(df_last_sent, on=COL_ID, how='left')
    df_reference = df_reference[df_reference[COL_DATE] == df_reference['Ultima_Compra_Enviada']].copy()

    
    # 2. Criar a mensagem na DF de Referência (apenas 1 linha por cliente)
    def create_message(row):
        cliente_full_name = row[COL_NAME]
        detento_full_name = row[COL_DETENTO]
        last_order_date = row[COL_DATE].strftime('%d/%m/%Y') 
        client_first_name = str(cliente_full_name).strip().split(' ')[0].capitalize() 
        
        # Lógica de gênero
        if not detento_full_name or pd.isna(detento_full_name):
            detento_first_name = "a pessoa amada" 
            pronome = "ele/ela" 
            artigo_definido = "o/a"
        else:
            detento_first_name = str(detento_full_name).strip().split(' ')[0].capitalize()
            gender_parts = get_gender_parts(detento_first_name) 
            pronome = gender_parts['pronome']
            artigo_definido = gender_parts['article'] 

        # --- TEMPLATE DE MENSAGEM FINAL (CONSULTIVA) ---
        message = (
            f"Olá {client_first_name}! Aqui é a Sofia, sua consultora exclusiva da Jumbo CDP!\n\n"
            f"Percebi que o seu último jumbo para {artigo_definido} {detento_first_name} foi em {last_order_date}, então resolvi falar com você.\n\n"
            f"Quero garantir que {pronome} não fique sem os itens que precisa!\n\n"
            f"Você conseguiu identificar algum motivo para a pausa no envio? Estou aqui para te ajudar com o que precisar.\n\n"
            f"Conte comigo! 💛"
        )
        return client_first_name, message

    df_reference[COL_NAME] = df_reference[COL_NAME].astype(str).fillna('')
    data_series = df_reference.apply(create_message, axis=1)
    temp_df = pd.DataFrame(data_series.tolist(), index=df_reference.index) 
    df_reference[COL_OUT_NAME] = temp_df[0]
    df_reference[COL_OUT_MSG] = temp_df[1]
    
    # Colunas de referência para o Merge
    ref_cols = [COL_ID, COL_PHONE, COL_OUT_NAME, COL_OUT_MSG, 'Ultima_Compra_Enviada']

    # 3. Merge do Resultado Final com as Mensagens/Dados de Referência
    df_processed = df_full_output.merge(df_reference[ref_cols], on=COL_ID, how='left', suffixes=('_original', '_ref')).copy()
    
    # Garante que o nome e a mensagem sejam do DF de Referência (o que tem o CLIENT_FIRST_NAME e a MENSAGEM)
    df_processed[COL_OUT_NAME] = df_processed[COL_OUT_NAME + '_ref']
    df_processed[COL_OUT_MSG] = df_processed[COL_OUT_MSG + '_ref']
    df_processed[COL_PHONE] = df_processed[COL_PHONE + '_ref']
    
    # 5. Finalização das Métricas
    metrics['clientes_qualificados'] = len(clientes_aceleracao_ids) # Contamos o número de IDs únicos
    
    if df_processed.empty:
        return df_processed, metrics 

    # 6. Formatar colunas para exibição
    def format_brl(value):
        try:
            value_str = str(value).replace('R$', '').replace('.', '').replace(',', '.')
            return f"R$ {float(value_str):.2f}".replace('.', ',')
        except:
            return str(value)

    df_processed['Valor_BRL'] = df_processed[COL_TOTAL_VALUE + '_original'].apply(format_brl)
    df_processed['Data_Referencia'] = df_processed[COL_DATE + '_original'].dt.strftime('%d/%m/%Y')
    
    return df_processed, metrics


# --- Interface do Usuário (Streamlit) ---

# Seção de Upload
st.header("1. Upload do Relatório de Vendas (Excel/CSV)")
st.markdown(f"#### Colunas Esperadas: {COL_ID}, {COL_NAME}, {COL_PHONE}, {COL_STATUS}, {COL_ORDER_ID}, **{COL_DATE}**, {COL_TOTAL_VALUE}, **{COL_DETENTO}**")

uploaded_file = st.file_uploader(
    "Arraste ou clique para enviar o arquivo.", 
    type=["csv", "xlsx"]
)

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_original = pd.read_csv(uploaded_file)
        else:
            df_original = pd.read_excel(uploaded_file, engine='openpyxl')
            
        st.success(f"Arquivo '{uploaded_file.name}' carregado com sucesso!")
        
    except Exception as e:
        st.error(f"Erro ao ler o arquivo. Erro: {e}")
        st.stop()


    # Botão de Processamento
    st.header("2. Iniciar Qualificação de Leads de Aceleração")
    if st.button("🚀 Processar Dados e Gerar Leads de Aceleração"):
        
        try:
            # Chama a função de processamento
            df_processed, metrics = process_data_aceleracao_v2(df_original) 
        except ValueError as ve:
            st.error(f"Erro de Processamento: {ve}")
            st.stop()
        
        # --- Seção de Resultados ---
        st.header("3. Lista de Disparo (Aceleração de Repetição)")
        
        col_met1, col_met2 = st.columns(2)
        col_met1.metric("Clientes Ativos Qualificados (IDs)", metrics['clientes_qualificados'])
        col_met2.metric("Total de Linhas no Relatório", len(df_processed))
        
        total_ready = metrics['clientes_qualificados']

        st.subheader(f"Leads para Aceleração ({total_ready} Clientes Únicos)")
        st.markdown("---")

        if total_ready == 0:
            st.info("Nenhum lead encontrado com o perfil: Última Compra Enviada EXATAMENTE 28 dias atrás E Houve Nova Interação.")
        else:
            
            # Funções Auxiliares para Exibir Tabela e Botões (Cor Verde)
            
            def render_lead_table(df_display, title, color_code):
                st.subheader(f"✅ {title} ({df_display[COL_ID].nunique()} Clientes Únicos)")
                st.markdown("---")

                # Headers
                col_headers = st.columns([1.5, 1.2, 1.2, 1.2, 1.5, 5]) 
                col_headers[0].markdown("**Cliente (Status Atual)**") 
                col_headers[1].markdown(f"**Data do Pedido**") 
                col_headers[2].markdown(f"**N. Pedido**") 
                col_headers[3].markdown(f"**{COL_TOTAL_VALUE}**") 
                col_headers[4].markdown(f"**Status da Linha**") 
                col_headers[5].markdown("**Ação (Disparo)**")
                st.markdown("---")

                for index, row in df_display.iterrows():
                    cols = st.columns([1.5, 1.2, 1.2, 1.2, 1.5, 5]) 
                    
                    # Dados do Pedido (colunas _original)
                    pedido_status = row[COL_STATUS + '_original']
                    pedido_data = row['Data_Referencia']
                    pedido_valor = row['Valor_BRL']
                    pedido_numero = row[COL_ORDER_ID + '_original']
                    
                    # Dados de Referência (colunas _ref - IGUAIS POR CLIENTE)
                    cliente_first_name = row[COL_OUT_NAME]
                    message_text = row[COL_OUT_MSG]
                    phone_number = "".join(filter(str.isdigit, str(row[COL_PHONE])))
                    
                    # Apenas a primeira linha de cada cliente recebe o botão
                    if index == df_display.index[0] or row[COL_ID + '_original'] != df_display.iloc[index-1][COL_ID + '_original']:
                        
                        encoded_message = quote(message_text)
                        whatsapp_link = f"https://wa.me/55{phone_number}?text={encoded_message}"

                        whatsapp_button_html = f"""
                        <a href="{whatsapp_link}" target="_blank" style="
                            display: inline-block; 
                            padding: 8px 12px; 
                            background-color: {color_code}; 
                            color: white; 
                            border-radius: 4px; 
                            border: 1px solid #128C7E;
                            text-decoration: none;
                            cursor: pointer;
                            white-space: nowrap;
                        ">
                        ▶️ WhatsApp
                        </a>
                        """
                        cols[5].markdown(whatsapp_button_html, unsafe_allow_html=True) 

                    # 1. Exibe os dados
                    # Exibe o Nome apenas na primeira linha do ID
                    display_name = cliente_first_name if index == df_display.index[0] or row[COL_ID + '_original'] != df_display.iloc[index-1][COL_ID + '_original'] else f"ID: {row[COL_ID + '_original']}"
                    
                    cols[0].write(display_name)
                    cols[1].write(pedido_data)
                    cols[2].write(pedido_numero)
                    cols[3].write(pedido_valor)
                    cols[4].markdown(f"**{pedido_status}**") # Destaque do status para a linha

                st.markdown("---")

            
            # --- Renderizar Segmento Único ---
            render_lead_table(df_processed, "Relatório Detalhado", "#25D366") 

            # --- Botão de Download ---
            df_export = df_processed[[COL_ID + '_original', COL_NAME + '_ref', COL_DETENTO + '_original', COL_PHONE + '_ref', COL_STATUS + '_original', COL_ORDER_ID + '_original', COL_TOTAL_VALUE + '_original', 'Data_Referencia', COL_OUT_MSG]].copy()
            
            df_export.rename(
                columns={
                    COL_ID + '_original': COL_ID, 
                    COL_NAME + '_ref': COL_NAME,
                    COL_DETENTO + '_original': COL_DETENTO,
                    COL_PHONE + '_ref': COL_PHONE,
                    COL_STATUS + '_original': COL_STATUS, 
                    COL_ORDER_ID + '_original': COL_ORDER_ID, 
                    COL_TOTAL_VALUE + '_original': COL_TOTAL_VALUE, 
                    'Data_Referencia': 'Data do Pedido', 
                    COL_OUT_MSG: 'Mensagem_Referencia'
                },
                inplace=True)
            
            csv_data = df_export.to_csv(index=False, sep=';', encoding='utf-8').encode('utf-8')
            st.download_button(
                label="📥 Baixar Lista de Aceleração Completa (CSV)",
                data=csv_data,
                file_name='clientes_aceleracao_detalhado.csv',
                mime='text/csv',
            )
