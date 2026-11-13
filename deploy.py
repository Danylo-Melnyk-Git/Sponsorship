"""Operator-only account management and bounded research/draft worker."""
import argparse
import getpass
import time
from packages.runtime.config import Settings
from packages.runtime.auth import AuthStore, ROLES

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="command",required=True)
    user=sub.add_parser("user-add"); user.add_argument("username"); user.add_argument("--role",choices=ROLES,required=True)
    disable=sub.add_parser("user-disable"); disable.add_argument("username")
    reset=sub.add_parser("user-password"); reset.add_argument("username")
    role=sub.add_parser("user-role"); role.add_argument("username"); role.add_argument("--role",choices=ROLES,required=True)
    sub.add_parser("worker")
    args=p.parse_args(); settings=Settings.from_env()
    if args.command=="worker":
        from packages.runtime.jobs import JobStore
        from packages.runtime.research_jobs import process_once
        from packages.domain.service import ResearchService
        from packages.domain.storage import open_store
        store=JobStore(settings.jobs_database); service=ResearchService(open_store(settings.database))
        while True:
            # Search jobs import through the role contract; draft jobs stay unimported drafts.
            if not process_once(store, service): time.sleep(2)
    auth=AuthStore(settings.auth_database)
    if args.command=="user-add": auth.add_user(args.username,getpass.getpass("Password (15+ characters): "),args.role)
    if args.command=="user-disable": auth.change_user(args.username,active=False)
    if args.command=="user-password": auth.change_user(args.username,password=getpass.getpass("New password: "))
    if args.command=="user-role": auth.change_user(args.username,role=args.role)
    print("Account updated; existing sessions revoked where applicable.")

if __name__=="__main__": main()
