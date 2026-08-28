import {createContext,useContext,useState, type ReactNode} from 'react'; import type {Role} from '../types/api';
const Context=createContext<{role:Role;setRole:(r:Role)=>void}|undefined>(undefined);
export function UserProvider({children}:{children:ReactNode}){const [role,setRole]=useState<Role>('farm_manager');return <Context.Provider value={{role,setRole}}>{children}</Context.Provider>};
export const useUser=()=>{const c=useContext(Context);if(!c)throw new Error('UserProvider required');return c};
