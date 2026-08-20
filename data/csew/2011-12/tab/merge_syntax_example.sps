* Encoding: UTF-8.

*Pick up existing dataset (change '2011-12' to the appropriate year and adjust path)*
GET
  FILE='Data\2011-12\VF_2011-12.sav'.

*Create new version with variables from bolt on dataset dropped.*
SAVE OUTFILE='Data\CSEW Apr11Mar12 VF - to merge.sav'
 /DROP=  vandalis_vf to vioprc_vf
 vandalis_vfnocap to vioprc_vfnocap	
 vandalis_vf_rp to vioprc_vf_rp
 c11indivwgt
 c11hhdwgt
 c11weighti.

*merge new version with bolt on dataset.*
MATCH FILES FILE='Data\CSEW Apr11Mar12 VF - to merge.sav'
 /TABLE='Data\CSEW Apr11Mar12 VF bolt on.sav'
 /BY rowlabel.

*Save new dataset. 
SAVE OUTFILE='Data\CSEW Apr11Mar12 VF - New Variables.sav'.
