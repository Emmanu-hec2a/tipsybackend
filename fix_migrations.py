import os
import re

migrations_dir = 'urbanfoods/migrations'

for filename in os.listdir(migrations_dir):
    if filename.endswith('.py'):
        filepath = os.path.join(migrations_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Replace all CheckConstraint(condition= with CheckConstraint(check=
        # This regex handles both single-line and multi-line cases
        updated = re.sub(
            r'CheckConstraint\(\s*condition=',
            'CheckConstraint(check=',
            content
        )
        
        if updated != content:
            with open(filepath, 'w') as f:
                f.write(updated)
            print(f"✅ Fixed {filename}")
        else:
            print(f"⏭️  {filename} - no changes needed")

print("\n✅ All migration files fixed!")
