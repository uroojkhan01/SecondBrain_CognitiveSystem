# assistant_backend_1/schema.py
"""
Notion Workspace Schemas
-------------------------
This module defines the database schemas used to build and validate the Notion workspace.
"""

CAPTURE_SCHEMA = {
    "Content/Message": {"title": {}},
    "Capture Timestamp": {"date": {}},
    "Set Reminder?": {"checkbox": {}},
    "Reminder Date/Time": {"date": {}},
    "Processed Status": {"select": {"options": [
        {"name": "Unprocessed", "color": "red"}, 
        {"name": "Moved to Area", "color": "green"},
        {"name": "Archived", "color": "gray"}
    ]}},
    "Proposed Area (AI)": {"select": {"options": [
        {"name": "Health & Fitness", "color": "red"},
        {"name": "Finance & Wealth", "color": "green"},
        {"name": "Career & Professional", "color": "blue"},
        {"name": "Personal Growth", "color": "purple"},
        {"name": "Home & Lifestyle", "color": "yellow"}
    ]}},
    "Proposed Project (AI)": {"rich_text": {}},
    "Input Type": {"select": {"options": [
        {"name": "Text", "color": "default"}, 
        {"name": "Link", "color": "blue"}, 
        {"name": "Voice Note", "color": "purple"},
        {"name": "Image", "color": "yellow"}
    ]}},
    "Actionability": {"select": {"options": [
        {"name": "Actionable Task", "color": "red"}, 
        {"name": "Reference Only", "color": "blue"}, 
        {"name": "Someday/Maybe", "color": "yellow"}
    ]}}
}

GLOBAL_AREA_SCHEMA = {
    "Name": {"title": {}},
    "Date Logged": {"date": {}},
    "AI Executive Summary": {"rich_text": {}}
}

AREA_SPECIFICS = {
    "Health & Fitness": {
        "Sub-Category": {"select": {"options": [{"name": "Nutrition"}, {"name": "Workout"}, {"name": "Sleep"}, {"name": "Mental Health"}]}},
        "Biometric/Value": {"rich_text": {}},
        "Energy Level": {"select": {"options": [{"name": "High"}, {"name": "Medium"}, {"name": "Low"}]}}
    },
    "Finance & Wealth": {
        "Transaction Type": {"select": {"options": [{"name": "Expense Idea"}, {"name": "Income Stream"}, {"name": "Investment Research"}]}},
        "Estimated Amount": {"number": {"format": "dollar"}},
        "Financial Entity": {"rich_text": {}}
    },
    "Career & Professional": {
        "Professional Domain": {"select": {"options": [{"name": "Networking"}, {"name": "Skill Acquisition"}, {"name": "Work Project"}]}},
        "Associated Company/Person": {"rich_text": {}},
        "Impact Score": {"select": {"options": [{"name": "High Impact"}, {"name": "Routine Maintenance"}]}}
    },
    "Personal Growth & Learning": {
        "Media Format": {"select": {"options": [{"name": "Book"}, {"name": "Article"}, {"name": "Podcast"}, {"name": "Course"}]}},
        "Key Takeaway": {"rich_text": {}},
        "Application": {"rich_text": {}}
    },
    "Home & Lifestyle": {
        "Asset/Domain": {"select": {"options": [{"name": "Vehicle"}, {"name": "Apartment"}, {"name": "Hobbies"}, {"name": "Family"}]}},
        "Cost Estimate": {"number": {}},
        "Urgency": {"select": {"options": [{"name": "Immediate"}, {"name": "Seasonal"}, {"name": "Low Priority"}]}}
    }
}

PROJECTS_SCHEMA = {
    "Project Name": {"title": {}},
    "The 'Big Why'": {"rich_text": {}},
    "Target Deadline": {"date": {}},
    "Status": {"select": {"options": [
        {"name": "Proposed", "color": "blue"}, 
        {"name": "Active", "color": "green"},
        {"name": "Paused", "color": "yellow"},
        {"name": "Completed", "color": "gray"}
    ]}},
    "Progress Bar": {"number": {}}, 
    "Celebration Reward": {"rich_text": {}}
}

TASKS_SCHEMA = {
    "Task Name": {"title": {}},
    "Execution Date": {"date": {}},
    "Requirement Level": {"select": {"options": [{"name": "Mandatory", "color": "red"}, {"name": "Optional", "color": "gray"}]}},
    "Criticality": {"select": {"options": [
        {"name": "P1 - Critical", "color": "red"}, 
        {"name": "P2 - Important", "color": "yellow"}, 
        {"name": "P3 - Minor", "color": "blue"}
    ]}},
    "Energy Required": {"select": {"options": [
        {"name": "High Focus", "color": "red"}, 
        {"name": "Medium", "color": "yellow"}, 
        {"name": "Low/Braindead", "color": "green"}
    ]}},
    "Time Block": {"select": {"options": [
        {"name": "Morning", "color": "yellow"}, 
        {"name": "Afternoon", "color": "orange"}, 
        {"name": "Evening", "color": "blue"}
    ]}},
    "Estimated Duration": {"number": {}}, 
    "Rollover Count": {"number": {}}
}
