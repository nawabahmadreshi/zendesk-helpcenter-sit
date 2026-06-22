from app.user_model import UserModel
import os

def test_mastery_saturation():
    print("\n--- Testing Mastery Saturation ---")
    db_path = "storage/test_user_model.db"
    if os.path.exists(db_path): os.remove(db_path)
    
    model = UserModel(db_path=db_path)
    user_id = "test_user_Alpha"
    component_id = "basics"
    
    # Initial mastery should be 0
    m0 = model.get_mastery(user_id, component_id)
    print(f"Initial mastery: {m0:.2f}")
    
    # Simulate 5 interactions
    for i in range(5):
        model.record_interaction(user_id, component_id)
        print(f"Interaction {i+1}, mastery: {model.get_mastery(user_id, component_id):.2f}")
    
    m5 = model.get_mastery(user_id, component_id)
    
    if m5 > m0:
        print(f"✅ Mastery increased from {m0:.2f} to {m5:.2f}")
    else:
        print("❌ Mastery failed to increase.")

    # Check suppression threshold
    if m5 > 0.5:
        print("✅ Mastery on track for suppression (threshold 0.8)")
    
    if os.path.exists(db_path): os.remove(db_path)

if __name__ == "__main__":
    test_mastery_saturation()
