import streamlit as st

# New GCP URL
NEW_URL = "https://tax-lookup-751008504644.us-west1.run.app"

st.set_page_config(page_title="Site Moving", layout="centered")

# Auto-redirect after 10 seconds using HTML meta refresh
st.markdown(f"""
    <meta http-equiv="refresh" content="10;url={NEW_URL}">
""", unsafe_allow_html=True)

st.warning("⚠️ **This site is being deprecated**")

st.markdown(f"""
## 🚚 We've Moved!

This application has moved to a new location:

### **[{NEW_URL}]({NEW_URL})**

Please update your bookmarks.

---

You will be automatically redirected in **10 seconds**...

Or [click here to go now]({NEW_URL})
""")

