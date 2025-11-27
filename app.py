import streamlit as st
import openai
import pandas as pd
from datetime import datetime
import base64
from fpdf import FPDF
import tempfile
import os
import hashlib

# Configuration de la page
st.set_page_config(
    page_title="GlycoAnalyzer Sénégal",
    page_icon="🩸",
    layout="wide"
)

# === GESTION DES LICENCES ===
def verifier_licence(email, password):
    try:
        licences = charger_licences()
        if email in licences['email'].values:
            ligne = licences[licences['email'] == email].iloc[0]
            if ligne['password'] == password and ligne['statut'] == 'active':
                if pd.to_datetime(ligne['date_expiration']) > datetime.now():
                    if ligne['photos_restantes'] > 0:
                        return True, ligne.to_dict()
                    else:
                        return False, "❌ Plus de photos disponibles"
                else:
                    return False, "❌ Licence expirée"
            else:
                return False, "❌ Mot de passe incorrect ou licence inactive"
        else:
            return False, "❌ Email non trouvé"
    except Exception as e:
        return False, f"❌ Erreur de vérification: {str(e)}"

def charger_licences():
    """
    Charge les licences - version simplifiée avec seul médecin test
    """
    try:
        # UNIQUEMENT le médecin test
        data = {
            'email': ['test@medecin.com'],
            'password': ['TEST@SD2025#'],
            'nom_medecin': ['Dr. Test Médecin'],
            'structure': ['Centre de Santé Test'],
            'type_licence': ['Découverte'],
            'date_creation': ['2024-12-20'],
            'date_expiration': ['2025-06-20'],
            'photos_restantes': [50],
            'statut': ['active']
        }
        
        df = pd.DataFrame(data)
        df['date_creation'] = pd.to_datetime(df['date_creation'])
        df['date_expiration'] = pd.to_datetime(df['date_expiration'])
        
        return df
        
    except Exception as e:
        # Retourner un DataFrame vide en cas d'erreur
        return pd.DataFrame(columns=[
            'email', 'password', 'nom_medecin', 'structure', 
            'type_licence', 'date_creation', 'date_expiration',
            'photos_restantes', 'statut'
        ])

def decrementer_photos(email):
    # Dans cette version cloud, on ne peut pas modifier le CSV distant
    # On gère en session seulement
    return True

# === 1. CONNEXION MÉDECIN ===
def authenticate():
    st.sidebar.title("🔐 Connexion Médecin")
    
    if st.session_state.get('connected'):
        medecin_info = st.session_state.medecin_info
        st.sidebar.success(f"✅ Connecté : {medecin_info['nom_medecin']}")
        st.sidebar.info(f"📷 Photos restantes : {medecin_info['photos_restantes']}")
        
        if st.sidebar.button("🚪 Déconnexion"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        return True
    
    email = st.sidebar.text_input("📧 Email")
    password = st.sidebar.text_input("🔒 Mot de passe", type="password")
    
    if st.sidebar.button("🔑 Se connecter"):
        if email and password:
            with st.spinner("Vérification..."):
                succes, message = verifier_licence(email, password)
            if succes:
                st.session_state.connected = True
                st.session_state.medecin_email = email
                st.session_state.medecin_info = message
                st.sidebar.success("✅ Connexion réussie")
                st.rerun()
            else:
                st.sidebar.error(message)
        else:
            st.sidebar.warning("⚠️ Veuillez remplir tous les champs")
    
    return False

# === 2. IDENTIFICATION PATIENT ===
def patient_form():
    st.header("1. 👤 Identification Patient")
    
    with st.form("patient_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            nom_complet = st.text_input("Nom complet du patient*", placeholder="Moussa Diallo")
            telephone = st.text_input("Téléphone* (9 chiffres)", placeholder="761234567", max_chars=9)
            
        with col2:
            type_diabete = st.selectbox(
                "Type de diabète*", 
                ["", "Type 1", "Type 2", "Grossesse"]
            )
            traitement = st.selectbox(
                "Traitement*",
                ["", "Insuline", "ADO", "Mesures hygiéno-diététiques"]
            )
        
        submitted = st.form_submit_button("✅ Ajouter patient")
        
        if submitted:
            if not all([nom_complet, telephone, type_diabete, traitement]):
                st.error("⚠️ Tous les champs obligatoires doivent être remplis")
                return None
            
            if len(telephone) != 9 or not telephone.isdigit():
                st.error("⚠️ Le téléphone doit contenir 9 chiffres")
                return None
            
            return {
                "nom_complet": nom_complet,
                "telephone": telephone,
                "type_diabete": type_diabete,
                "traitement": traitement,
                "date_ajout": datetime.now()
            }
    
    return None

# === 3. UPLOAD + 4. ANALYSE PHOTOS ===
def analyser_photo(image_file):
    try:
        # Réinitialiser le pointeur du fichier
        image_data = base64.b64encode(image_file.getvalue()).decode('utf-8')
        
        client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model="gpt-4-vision-preview",
            messages=[{
                "role": "user", 
                "content": [
                    {
                        "type": "text", 
                        "text": "Extrait uniquement la valeur numérique de glycémie en g/L. Réponds uniquement avec le chiffre. Exemple: 1.20"
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                    }
                ]
            }],
            max_tokens=10
        )
        
        reponse = response.choices[0].message.content.strip()
        # Nettoyer la réponse pour garder seulement les chiffres et points
        valeur_text = ''.join(c for c in reponse if c.isdigit() or c == '.')
        valeur = float(valeur_text)
        
        return valeur
        
    except Exception as e:
        st.error(f"❌ Erreur lors de l'analyse: {str(e)}")
        return None

# === GÉNÉRATION RAPPORT PDF ===
def generer_rapport_pdf(resultat):
    try:
        pdf = FPDF()
        pdf.add_page()
        
        # Entête
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "RAPPORT GLYCÉMIQUE", 0, 1, 'C')
        pdf.ln(5)
        
        # Informations patient
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "INFORMATIONS PATIENT", 0, 1)
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, f"Nom complet: {resultat['nom_complet']}", 0, 1)
        pdf.cell(0, 8, f"Téléphone: {resultat['telephone']}", 0, 1)
        pdf.cell(0, 8, f"Type de diabète: {resultat['type_diabete']}", 0, 1)
        pdf.cell(0, 8, f"Traitement: {resultat['traitement']}", 0, 1)
        pdf.ln(5)
        
        # Résultats analyse
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "RÉSULTATS ANALYSE", 0, 1)
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, f"Date et heure: {resultat['date'].strftime('%d/%m/%Y à %H:%M')}", 0, 1)
        pdf.cell(0, 8, f"Valeur glycémique: {resultat['valeur']} g/L", 0, 1)
        
        # Statut avec couleur
        statut = resultat['statut']
        if statut == "Normal":
            couleur = "🟢 NORMAL"
        elif statut == "Hyper":
            couleur = "🔴 HYPERGLYCÉMIE"
        else:
            couleur = "🟠 HYPOGLYCÉMIE"
        
        pdf.cell(0, 8, f"Statut: {couleur}", 0, 1)
        pdf.cell(0, 8, f"Recommandation: {resultat['message']}", 0, 1)
        pdf.ln(10)
        
        # Pied de page
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, f"Rapport généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", 0, 1, 'C')
        
        # Sauvegarde temporaire
        nom_fichier = f"rapport_{resultat['nom_complet'].replace(' ', '_')}_{resultat['date'].strftime('%Y%m%d_%H%M')}.pdf"
        pdf.output(nom_fichier)
        
        return nom_fichier
        
    except Exception as e:
        st.error(f"❌ Erreur génération PDF: {str(e)}")
        return None

# === 5. TABLEAU RÉCAPITULATIF ===
def afficher_tableau():
    if 'resultats' not in st.session_state or not st.session_state.resultats:
        return
    
    st.header("3. 📊 Tableau des Analyses")
    
    # Création du tableau
    for i, resultat in enumerate(st.session_state.resultats):
        col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 1, 1, 1, 1, 2, 1])
        
        with col1:
            st.write(f"**{resultat['nom_complet']}**")
            st.caption(f"📞 {resultat['telephone']}")
            st.caption(f"🩺 {resultat['type_diabete']} - {resultat['traitement']}")
        
        with col2:
            st.write(resultat['date'].strftime("%d/%m"))
            st.caption(resultat['date'].strftime("%H:%M"))
        
        with col3:
            st.metric("Valeur", f"{resultat['valeur']} g/L")
        
        with col4:
            # Création miniature
            st.image(resultat['photo_data'], width=60, caption="Photo")
        
        with col5:
            statut = resultat['statut']
            if statut == "Normal":
                st.success("🟢 Normal")
            elif statut == "Hyper":
                st.error("🔴 Hyper")
            else:
                st.warning("🟠 Hypo")
        
        with col6:
            message = resultat['message']
            if "simple" in message.lower():
                icone = "☑️"
                couleur = st.info
            elif "urgence" in message.lower():
                icone = "🚨"
                couleur = st.error
            else:
                icone = "📞"
                couleur = st.warning
            
            couleur(f"{icone} {message}")
        
        with col7:
            nom_fichier = generer_rapport_pdf(resultat)
            if nom_fichier:
                with open(nom_fichier, "rb") as f:
                    st.download_button(
                        label="📥 PDF",
                        data=f,
                        file_name=nom_fichier,
                        mime="application/pdf",
                        key=f"dl_{i}"
                    )
            # Nettoyage
            try:
                os.remove(nom_fichier)
            except:
                pass

# === APPLICATION PRINCIPALE ===
def main():
    st.title("🩸 GlycoAnalyzer Sénégal")
    st.markdown("---")
    
    # Vérification connexion
    if not authenticate():
        st.info("🔐 Veuillez vous connecter dans la barre latérale")
        return
    
    # Vérification photos restantes
    medecin_info = st.session_state.medecin_info
    if medecin_info['photos_restantes'] <= 0:
        st.error("""
        ❌ Plus de photos disponibles dans votre licence.
        
        **Pour recharger :**
        📱 Envoyez un message WhatsApp  
        💰 Pack 50 photos : 10.000 FCFA  
        💰 Pack 100 photos : 18.000 FCFA
        """)
        return
    
    # Section identification patient
    nouveau_patient = patient_form()
    
    if nouveau_patient:
        st.header("2. 📸 Analyse Photos Glycémie")
        
        photos_uploades = st.file_uploader(
            "Sélectionnez les photos des glucomètres",
            type=['jpg', 'jpeg', 'png'],
            accept_multiple_files=True,
            key="uploader"
        )
        
        if photos_uploades:
            st.info(f"📷 {len(photos_uploades)} photo(s) sélectionnée(s) - {medecin_info['photos_restantes']} photos restantes")
            
            for i, photo in enumerate(photos_uploades):
                if medecin_info['photos_restantes'] <= 0:
                    st.error("❌ Plus de photos disponibles dans votre licence")
                    break
                    
                with st.spinner(f"Analyse de la photo {i+1}/{len(photos_uploades)}..."):
                    valeur = analyser_photo(photo)
                    
                    if valeur is not None:
                        # Détermination statut et message
                        if valeur < 0.70:
                            statut = "Hypo"
                            message = "🚨 Consultation urgente recommandée - Contacter le médecin"
                        elif valeur > 1.10:
                            statut = "Hyper" 
                            message = "📞 Appel médecin nécessaire - Ajustement traitement possible"
                        else:
                            statut = "Normal"
                            message = "☑️ Situation stable - Continuer surveillance habituelle"
                        
                        # Sauvegarde résultat
                        resultat = {
                            **nouveau_patient,
                            'valeur': round(valeur, 2),
                            'statut': statut,
                            'message': message,
                            'date': datetime.now(),
                            'photo_data': photo
                        }
                        
                        if 'resultats' not in st.session_state:
                            st.session_state.resultats = []
                        st.session_state.resultats.append(resultat)
                        
                        # Décrémenter le compteur
                        st.session_state.medecin_info['photos_restantes'] -= 1
                        
                        st.success(f"✅ Analyse {i+1} terminée: {valeur} g/L - {statut}")
    
    # Affichage tableau récapitulatif
    afficher_tableau()
    
    # Bouton reset
    if st.session_state.get('resultats'):
        if st.button("🔄 Nouvelle analyse"):
            st.session_state.pop('resultats', None)
            st.rerun()

if __name__ == "__main__":
    main()
