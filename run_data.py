# run_data.py - launcher that runs data/main.py from repository root
import runpy

if __name__ == '__main__':
    runpy.run_path('data/main.py', run_name='__main__')
