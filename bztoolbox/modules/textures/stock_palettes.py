"""Built-in stock Battlezone palettes used by the MAP converter.

The palette payloads are exact 768-byte RGB ACT files (256 RGB triplets).
They are embedded as compressed text so PyInstaller builds do not need
additional binary data files.
"""
from __future__ import annotations

import base64
import zlib

STOCK_PALETTE_NAMES = (
    'achilles.act',
    'black.act',
    'brown.act',
    'elysium.act',
    'europa.act',
    'explode.act',
    'ganymede.act',
    'grey.act',
    'hblack.act',
    'hblue.act',
    'hbrown.act',
    'hcyan.act',
    'hgreen.act',
    'hgrey.act',
    'hplasblu.act',
    'hplasgrn.act',
    'hplasred.act',
    'hred.act',
    'htan.act',
    'hwhite.act',
    'hyellow.act',
    'interface.act',
    'io.act',
    'mars.act',
    'moon.act',
    'objects.act',
    'plasblue.act',
    'plasgrn.act',
    'plasred.act',
    'tan.act',
    'titan.act',
    'venus.act',
    'white.act',
)

_STOCK_PALETTES_B85 = {
    'achilles.act': 'c-muNU=S1#kdly)my%RbmN(K;F)=i-v9NG)aPal;2n`4b@%Jgn$tY>8ZS88^v~J!0J$ufaJbCl_^`}ps{Qv)7gqcZ$joF%u)t{FwS%4#(fny2>LyscI6aj`g5)5lC8TJNooJ$rs5yyQkmEl^8;=O8#=RJzg=V-oPYk6;u;k~7n_m+A+Uz_}XZ`Ai=LGRBM|NJ@i^|Qq7TLM?M8a3DGRwt`ZO%)8cW(shY@iSmH)!<Q)U|sFux^l(5nbW#|{ycpD#-0;<ryttYy=%?H<x3_mm|nkrMcaajS#u}mb~I(T)CQDf1SZ4<hj^M7doX4N%H@{j#%87YCq%hKhuQmh+SywgxH;?DTBur^DH-X?YiUZTC<u#-3h?pqbFr~=b6&iCcJu!Ab63roy0EQvLQPk9Ms;)Aqzaqdx{SiofQAC?<h+FbSeue;mGpGC$PB-dIQ8^+xv&_|h$zd{FvSWFHIFE#@Gx=TFug=yC95#|NN-smUz1o*mRxIDFHg-N4+(ouGcPwWUsv`(TWJFia|b8YSX0SpGcHdX2}fIDJtrMoCk7u=UT-rN2Mb|SOLcQ|Svw<9M`P9iO+h;&UUf?~Gb0fzLl#p*ej^h`O(R8TO(q=!A!k({Q!ODSLj^M}4ht<N6CFk^Lk2xf0X<DlB`sMKHAVvsMjaqh7Ese<P*fMwRp!)HVboCO(NJM9m*P}WVUSm4(2-+QQsmK4U=ULkR#9M(S71<-=GGJ8P?chkm0^&P;1ZW%5SQSV5oZvSU=S7J6cJ{S<!0s=;1m#K;1*yI<YMIEX5ipp=ip#qW?=w=$@8c8&7RUReM0l3-nzc7%C5HJw&uL1hRoWUl*-Du(z3|HqLAEt|BM{Zlnj@IREGcm8S3j9?Ct#yed3$>fj##g&(zawX{*^{JD4qMq?7{~>i;t&A7^muWl(Zu5Y=M%&%jX6z+lh7AkV<SkH!NTwqyy&ynp}(2M3_+e*l*m=2i',
    'black.act': 'c-s5V@c;i{Lj3&v^78Wf`ug_v_Wu6<@$vEb`T6zr_5J<*^XJcBzkdDx{rk_KKY#!J{rB(R|NlR@96ySN90C9d>i2*',
    'brown.act': 'c-s5V@c%z85kEh_yu7@=zP`P^y}!SIe0+R<etvy@eSd%d{Q2|OuV24^|Nism&)>g)|NZ;-|Nqn0F{5Y{p&<ay%=dr',
    'elysium.act': 'c-muNU=S1#kdly)my%RbmN(K;F)=i-v9NG)aPal;2n`4b@%Jgn$tY>8ZS88^v~J!0J$ufaJbCl_^`}ps{Qv)7gqcZ$joF%u)t{FwS%4#(fny2>LyscI6aj`g5)5lC8TJNooJ$rs5yyQkmEl^8;=O8#=RJzg=V-oPYk6;u;k~7n_m+A+Uz_}XZ`Ai=LGRBM|NJ@i^|Qq7TLM?M8a3DGRwt`ZO%)8cW(shY@iSmH)!<Q)U|sFux^l(5nbW#|{ycpD#-0;<ryttYy=%?H<x3_mm|nkrMcaajS#u}mb~I(T)CQDf1SZ4<hj^M7doX4N%H@{j#%87YCq%hKhuQmh+SywgxH;?DTBur^DH-X?YiUZTC<u#-3h?pqbFr~=bF#9sy1Cfu>8NGI_*z+8nrX?ZYp8nITP8(#c$h2NSQz<v*oJw#`ng)@s>%7e7=;G7hIrXJT55UN8pQ;;mZbRe@$%%vy649E<i-c&r39)fsnrx_%Snlax|_uXhnrg%IhY%YiU_t>r6mTtq(nH$OUYRp8|Z23S{f?FML0V-ScV7KIa*s}23o{Lg@y$BCP(>Bo!IT}Vp^IJR96_|V65op>1twZu>97Igdm3qZ`;bONHcAHJp*+YTO%7&tw3AD#Fzw2Z52mrr}ayw73Sn8dg=z+YML18$SFw0c$)^<C?p12E2+rYYs(}Cd*~S%_`29S7;EaPtAzTP<z}U7sLJJ~cxOboni#10*crLHyQnHi>l^6Ac-wX~H~6~w6{SZOMA)XML|YhWdDv)Mm}rN)>Sx8JIoKH0We3FsI%LGS2iaNGRF}((@|tL?g}JC(8d=%88he;(`UKdBi%IAziAF{EdfI!$1Xzc9hlT}4_%B-MVei54|35>0J%hcy-=R-@Ge5BB-s72ink{WLTWkljMU9kl07LzMhUDW6ZoLdjt_-4D4F4Gz>KPd985ral82Hh6Aj6g{0ht#Nz~JBjl>H9?UC{QK',
    'europa.act': 'c-muNU=S1#kdly)my%RbmN(K;F)=i-v9NG)aPal;2n`4b@%Jgn$tY>8ZS88^v~J!0J$ufaJbCl_^`}ps{Qv)7gqcZ$joF%u)t{FwS%4#(fny2>LyscI6aj`g5)5lC8TJNooJ$rs5yyQkmEl^8;=O8#=RJzg=V-oPYk6;u;k~7n_m+A+Uz_}XZ`Ai=LGRBM|NJ@i^|Qq7TLM?M8a3DGRwt`ZO%)8cW(shY@iSmH)!<Q)U|sFux^l(5nbW#|{ycpD#-0;<ryttYy=%?H<x3_mm|nkrMcaajS#u}mb~I(T)CQDf1SZ4<hj^M7doX4N%H@{j#%87YCq%hKhuQmh+SywgxH;?DTBur^DH-X?YiUZTC<u#-3h?pqbFr~=bN>GQ=kt%>ufKeI^7+f1H=i%RdUN{8>%(`R?!Nta{gpeb&)i;e`sUn|SLPhPG~>Ye$p_9&*?o4x?$bRx&-Cm#-oE2R$CkrwTTV1@Io!DZNW=R5)f)~ruRK|``atE%-G!@mS1mkTw0KA6qMaqP4-`z@oj+rB!t5<MlXhkFZBOpmlGeREv13cfgf(#;>tk9rM7OMps9zJ-uspJMYH-am|MDf?B@28?W_lFNaW9zWnlr~Gd#YPbmwm<*yNoW6)Ee95NjAwH=80`4vGu0WZ3ZzlHsSdO;WgS3m0H0S8X?6R0maGzh1y<eD&7SOKG_OD(j!~OBTL#PL&hap-8M|ZAwj}EMb<V_#XLmWB0$VKLBu9T#l&01I6&AuM&86*-Z((iEI`0CLSElTLEoLvBv?k*oku^ASI3J}(}rE$gGIrPQPGr9MwdZci$PS0fnSV)RPg^lLw!Aiy}jR|Pkb{!u;<?6nR=QnZ8ckL2eU<ulyU$={eOn!;|y-S3`(vHqFN0985rsr80;As<QW+F(Rd)kmMj687ZAYU-~g2U4*)~CCEW',
    'explode.act': 'c-s5V@c;iP8byN^{r~^{``-W0d;Z_6et)j``>~++d!wGOO}@9(>)uk!dvgrmueE$WNAr1);=O8#Yb}b`QW;Lfai2>T*c-&L){<e41j7^oh8{(ZDI5&h3>?V<9R9p))?BO_Y|J9eObiSR0Nh9DY5',
    'ganymede.act': 'c-mczQAiVE0LQ-^&XwjC8lH0H)Qgs#ajwfwcC`bq`ikW~ZPlt3SDSX}q(O%XuC_|+ss%~YCau`RqJ`5&NDZ4MC1oh(L$sop5tcy@N(SN6ve$lZe}4Rb0Du)5O%a9_7Znm^#rkrBuB2Fo;W=(MgnJRPm`yIHD4jdgd8PB=z`(OaV&e7dkICe>>FIPjov+ByDHVogndaq6yGGRvRDKokm8kq05X3-#H5jf}y|HV?j%2@Y0Pj0WQtjA`uVf~;ZnnQV6|79%txnzDHPdgO9X|NyW&P}%Qws~-KffP+JXm+XQ-8r-(QaSc-LPW6Ap_OmwUlC$E{DJ}`{1_wkvqLTR~HsuOnpd<4c~k|bag1&buZi%y6Jfkxftqdy4}?xpKtCsgCwy|II_pGbMq;<q^WLoOKZ#Frbe@HkUzA~Xxh2eSWRuO*|3FKW2h?CR}`18!w79&!AebTu6mg=D|_i>NCggTp$f7_1E<Hs9pgcFiCWo!s@&2sb6K8Yqwew*DcEztZ=&L7tqP^`i7bBo^i+RBoS&cHV>TODW>q1krm0r3{!z5MLPuz_vv<@mb{m>{5lJR)<>hJ0wD=`&^B2GUM)HGfT#IVfzm3YIR(-PhxWmGY`JIr+k2$z^gMOct8<R{S5k_q+ZZge9+!JB9gTif;_IKRpL$pZaBiEf_fkiA11HnnJHGr5lhTvH$WTAPQh>EaHfFyy(Tqa24Z5$Do5TnB)E>lS0LsoVoC<UzaWXu=y3N}b1$c|ojAf6T(V#LXRmIW_IB9^p}7)xt^1SKz|AWM$QjzN(}(I|)KcsargbvDGhXsrmzh-9%qI_9=IZG7AbW0GaW?_@}=jVF1QXyZsL;uEqE_X;jnCodjJY}7BgSnWhu28*QAz~cc%W9{=_xxI5)EvcODab;tl^02I6+(l&wc+$ZB3T(dyO1FWP<sc1!2LK}g#Q>=PTmNF=@V_2Hfa4Zz`Y*I~A-D',
    'grey.act': 'c-s5V@c;iP8ajxdpI=^HUSD6|-rnBd-#<P+K0iOdzP`S{zkmMx`RmuO-@kwV`Sa)R-@pI<{rms_M?;JN0sw4N_ka',
    'hblack.act': 'c-s5_|Nno6Q8bE1C;|X05dRM',
    'hblue.act': 'c-s5V@c;iP!hz)F<wpZyP@(tl-vi0@>(>Lx`ucj1;Q#;U&!3+^e|~;`zP-IYsRjZ7Egk$P',
    'hbrown.act': 'c-rIV=l{>}AA<Jp-~a#re>it=qWSaZ)4`Vf{Cs_V{XrfSqlhFVFE5WN2mtE{`I!',
    'hcyan.act': 'c-s5V@c%!<e|dTN|6s-_LPq@j{G)*|!07+~`Sa)d`}@O1&YwRIB;(`bF%|3U>yv6e0D1=ahy',
    'hgreen.act': 'c-s5V@c;iP8b!kf{r|sz|Ni*+czu0+etv#}>H*Fc`zr',
    'hgrey.act': 'c-s5V@LyhDUSD7TKf`}GijR-a&(E)~ukY{g2XgoC-+%u6`S<VNBdZyV=s$Mx`Sa()+3VM@$EDrh-ycZY+uOrM`1$z<yO&21We5Op(DvZ',
    'hplasblu.act': 'c-s5V@c%z4X#f8G=g*%9GTy&`|NlQ}dPmVHA{(t=zaGMvKYxCGeSLg<yuH0WT-M*;UteFJpP!#pV*zv``Gf',
    'hplasgrn.act': 'c-s5V@c%zq=>7Zm|NoPzmmr!ye?E|`udj!T#K*^DReAsZeIU7i|9-g0`t|E+<f>6LB#^zmy}Z0UKR-WyW&ZyDKoS7x@A-r',
    'hplasred.act': 'c-s5V@c%zq=>7Zm|NleT^78Wk$u$Rv)~{cWCNh8i{Qmxa2s=MNUteDzm)`sL?*qyG`}Y&H#oynb5=V}rA&vO?`LT)v09Zizv;',
    'hred.act': 'c-s5V@c%z$NMBzcNXEy<1IhgS{Qdj)|EJi@Q8bFEgZ}^T@9(#_x0jcf=jZ3gQ~&@`<@ZM',
    'htan.act': 'c-s5V@c%!<e|dR%AgQmf4<zmF?f-)XhX(rp|NZ;-=g*&qaQE-u4<y&GUk@bb&!6Al-(O!}pP!!}A0JPK;r#skLn$am5$Om3TeJ7_',
    'hwhite.act': 'c-s5V@c%!<e|dTN|6m3L+1uL#Nq>KTxJZ3{eSd%d`t|Gg@85s^{Q3L$@4tWl{{R2~$hrm`&7VIXt9X2TJe-}MpN~tszP>)12tPmnpz`1-qB;TqMVt44',
    'hyellow.act': 'c-s5V@c;kNLHhdo^78WZv5TLd|NoE*oKZv={r`Xd{Q3U={`mNKe}8|V2mq|2_*e',
    'interface.act': 'c-qyGQ4Pc}3_~A-LMVhn2!ui?ghB{}KnR3FD1<@?gh1GB5boooo#ju<w(L?$t+ll#BE9!9#+*}C&CK1`T6^zvPDEtpb%S@20u>qvbQmx}!N6g`h64e~BQMlSYlzT0V=yPGnBmS^?9Dkukog3BX@BFlh2FORU-N$J0~R2WG5',
    'io.act': 'c-mczOH9%M0Ed74-w4A0FGzqApeV+`z!D`>@Wrr1(ZZUgX{0H|W}0nfj+xq=)*4H5Zq{sRkD0Z#TAS0k+16vVj#d{sWO?Xd>(V^Y<Jfom_H7>kf#<bqwO*?+W$N=Rrri$v-onBPkH_!x1p|SDwbfmxJI)UD504H%dGu&yY3bdYH=jOy_`1HHNF<abk;9NhNpx*86XLm3;Kn&zF>>QPrqx(*VY!}rAL3s(OV--3He`(VsW+||H>P)NF1X^;j`*A_KDTdUA+)*N`0Hi;=KG$lt%>j7TAx3ydoY|gc+u7uGEcM#hl+?md3ueV%+HaU)bzZs^1=OEQ#Z!8wqAVxxb%8?a&>WR@nP)VY;0yS`uP6knOOK{EHZNG)KGumY)4&7^MQj^1wB4dxNdvoT%;-7Ufa@GaiqarT~*?C*}dht#f4c#&Wt>p-m*h&GAOpC@-mq`iD4z;FHWqd;iDGcSi~8u(RfE;g~BrmcQwpBh1(P+X^hFqs6g}z#2AGrg<c8~25l^wSOk+0B;cpvqfkm<4~;w;F2Dg;31rjA0@8sr8Yv=33CvXqu_Ez6fw<4gp0SEYN)_EsS*KMpn$7g-=`(t|Q%@h$F%bpPrXZRWL{LHa<)R9KtdNSzINa&ldHtmQ`f<~>!}_5{^I%YSzQH`|R}I$a2KK8iRByjfrRv&m?DlE<%alE3>Yh?X*rVy*n-VTo94}UN7AQNN@)J&>C0}UVEi~I@trkgxE%~TLT5aQxnYdt%q$VpVXym+E62Ff18n}`SNu`!8(XjbC@h&y%;z_HDaqv{Ok~YgogPhVPlL9B=NQi)Z1`Y<fG%PgC6f!9oD5R6nkVqwvLO@19A_6M{g?}Uxh(_Ud*R1}OP5odaap}ZcrhT4i8X*fWYBK|fCJ=fB?^R?}BGrNf5Cz<T9+3ZMe`m9^e}91hJf1%_@f(@w&M*',
    'mars.act': 'c-jE~1ONO0000pX5E>X59~v1XBOfv<Bs4KFJUBQ+KtN4MNL5f!R8LHBY-n_WeT9mJvaYVbyu8fG$=TP}<>ci5|Nj&N0w@LpI|>C)4F+Qn2x|Zcln4NfAqbQZ0Gt>AtvLX_QV7mt5XfE&)@1<JgdyI080U;3=bS0;tvTMDG2W#)-la<Ctz+-KTKC3M@6L1i`IYPDVYjqVsf99wd@XxpCzWLpS33ewLmW;p12rfNBp3y&NJXiro|%@5`T4`&*u2QSm%_S>x~!3>q>-SPf3K*9ppj~wk!^^AYlMAJbZAjvUQ<*_H*-h<YEd3-c5Pj1W=~*RL|axrOi4aJIWR^;E<HFUJ2oOREgvc=7$hJQ7Znf=4i5?j2MY<%nqbV5T*ib`wSQE<aZ9vtPqS`CsBcf3Z&b5oMzdl*s%1f_WJ;-EKcZnjn_^0>TRx~-J(*xZsaQ6lT0x;$Jfc`PoLNDPUr3x+JeF8Npj0+`U|XD2HkMU9mQ*&KP&k}WGmKP0mQXmBP&1HGIhjl^nM*W^Q8|=MFMCu-luI;_OfrH|JC#T-icB<#OE`*5FOWwtkVY$vM=*j)IfzFwmO(0lNi>Q@D}qQbcS<^XM>K*&EoV$bi9acNMJ|LtDu+EHaz!wGKP`SeCU`zAhczW~JuYTIJ9s)JeKjR$J}q)NC4Dm<b2B7YJUnMLDswR&X*D8fFdlL$9auChYAPFDE+J$o8cZ)NTqzl4BN$I99bF<9RUsBmAr(~{6-FTzO&b$F9v4O#5k40WHW?8$5)3aC3@r@{CJ+fF2?!nt2NVVb0RRBMd|SVISig5vzjaZ+b4|Z-O22MLzidOlYCykeJilc*zhgGPVKTp8FTY$Xzgj2&|Nj7ge*ix}PQvmIneYc~-VBw?24<@UU5EoXd>SKA0Du1gW5)nSjQ}D=02L|#{{R4g002J#03QGV4*>rF0Dk}gKL7w9000jF0RR60q@)0Ue*jQW06;(h{{a8eMh$T',
    'moon.act': 'c-ocBTS!xJ00!`XUgo?{ysag!>B)|^=}~8%u~R#+qx{vA`>V%1=uuDXXa}7+*h<04@-EGgffs}oJ}4<(f+zw}1cOo%AGKcAi{(QPMla#hny<a}@q79B-~#}ps8kxYTC2H=<!Va`Fk>-6kt9RY_aJOUh_kUyhwL629D6qQW^;3Qd;9R<;OoiB_tVo*D3lf%fh!`-anZI!g<YlW2Fe*Fn9?a{R3M-R8z!(*uROA=_S@o*JHYX%E;yh*o6?;H^3OL+!9a0v*%Vx^KHIRL?==7USbu)xy11DA`QyR+w{@#yB_kfgfc@rdM@o}90$H<aiO4cM0aHh>!HU(DmkV>gi;EB6zHIOB%<paaw$}Zxmi&wJ-q$PRi~g<`{+`L<?$JTymg~f}2Ck~y1+R3~W%oSkY3=H?iOo#QeG6N4*J2_nt%Y~U8|K?NB?fIlz8brpnwhRjN=lAX#KgzG+dZ5Mtovq{#-{^=<8%GP(=LzCIW*VXKhf<T>GJqH9zU0QpGuAaF--1ncTNa$pCGwg93#Bs;zehp?B&E>PH;3x14!&cf&=j~EB3L1n-w0hoK(X<tmYk1a6#S)IT><xh}s$6$#4z^NenAkxlSu;r#T0WWSSLe*knPHg>9jbOtE1S1qF&}Ftef=Hj%7E!Z4AfZRJoXXBx^F-Uvk_6DAmG-bmGy(zarnBN&081%l#=XugQ5DI#GZ$rvc!Kp{P8(;FFmDSeCLa1!ApiyK*-pmBo2^%Q1=SSgDU5W~q_J*CShwRvS(Sg}TDP-o|7T+2&S=cHt0C#Px>RhjXLsj+d%3T1p$v@#+h3jA+EA>j1_i=}q&chbVIn4Vz5>}N&inxb_wlJsbD5%7k9{S&Bs4st3$dI1Ol;03?}fEIw{f7<2Q($eK0LV%{jYv?b{<?<>',
    'objects.act': 'c-muNU=S1#kdly)my%RbmN(K;F)=i-v9NG)aPal;2n`4b@%Jgn$tY>8ZS88^v~J!0J$ufaJbCl_^`}ps{Qv)7gqcZ$joF%u)t{FwS%4#(fny2>LyscI6aj`g5)5lC8TJNooJ$rs5yyQkmEl^8;=O8#=RJzg=V-oPYk6;u;k~7n_m+A+Uz_}XZ`Ai=LGRBM|NJ@i^|Qq7TLM?M8a3DGRwt`ZO%)8cW(shY@iSmH)!<Q)U|sFux^l(5nbW#|{ycpD#-0;<ryttYy=%?H<x3_mm|nkrMcaajS#u}mb~I(T)CQDf1SZ4<hj^M7doX4N%H@{j#%87YCq%hKhuQmh+SywgxH;?DTBur^DH-X?YiUZTC<u#-3h?pqbFr~=bN*-eKZ*trfr$Eg277zIL!bC&eqhhN$20XbTiR;2*bZik8Y$%fhWh^u$;TPodKr{l8AP>!IvDC180;As<QW+F(Rd)kmMj687ZAYU-~cim0Frr(UH',
    'plasblue.act': 'c-s5V@c;iP8b$O%{QUg#^78un`u6tr{{H^)@$vcj`Stbn{r&y(=g(iie*OOa`_G?0fB*jd_wV2T|4(!G003B?_ka',
    'plasgrn.act': 'c-s5V@c;iP8bvU~&(AL}FR!n!Z*On!@9!TUAD^F}UteF}-`_uf{`~dp*YDrI|NQy$_wV0-|Ni~||3lut0OE1?fB',
    'plasred.act': 'c-s5V@c;iP8b#zHetv#=d3k+(eS3R*e}Dh@`1t(%{QCO({{H^?^XIQ$zkdJz{pZi0zkmP!`}gnv{~vVj2LK(9_ka',
    'tan.act': 'c-s5V@c%z4h@YQdUS3{bU*F!|-rwIpK0ZD_Kfk`dzQ4bJ{`~pt*RS8dfB*UO=kMRY|Ni~^|Nludd=!l$IwJs+z4w3',
    'titan.act': 'c-mczTS!xJ0Ed6Nf7@}>dGwrZr+I2;bF0monb<D5+KDzj+SH@2yp*C0qr5~=No2NemgTxEykJ=Pprw=r5d@(G23;t6%z9Zbl@C1_y@XF|z6RgJ?*boy9GW(AoXNP}nr|vDu$F8u@_9S~QLK`r{jwac2_5e~a`Hm|!1aM=PoBJ*pa1y&{nw?XAK$+xlSx*QZdWQw)$3}qlo6Wh0yRt_W~PQ|OmLX<Vxf-u6rta>YCd=1^JR0Qk6VtJmnR%6bKb<n_QbR|F<rSl7g<?o{`;nG<<p7P)sbI6+h07dogFB?bk^Ay**wyb(@>f&@8zqD6g%vhR&L!RDL6ZGe|&Ukb@lbPFZ1sf#ui@=y?h*hI2E59i$0yXG8yl@7w;Lo*mb#IK6#|Jt+hT};XWayb=Gd|>FsIhJY3V(95{HuAF9~x_ZF4yE!^d?mAWj&PE&z{vkHtsM{Bj&YNbk(u{c`!;CBD?Dc@}GrrW(uqaF6U5iZugJKkW9g>#NIm0zg03|1JgO6oJ^TwhRgZkOt`k2$(WXb!kf?NoK|%<Xnljb2Nui)ky#=yEFCo$6qTqkT(y!<Ou32MOEBAq%P6OgCCc*h)mlh9)!0HtF3CA#5VDnS@P{1%w0=5)d?JNdgfCZHPxGk4St9cmy`UlR#=QK;((YLoyJ_056{vFpxkh<WV9=L=HZV_&7Luro@<0$Y+QQadE`WL1f@dkwaW8akFshsX`sG8M0h73R&26l$}j?(rNjuVuvPeTPAGT#HNLyC3&<`&|<3!b_zxfu@e~8uo4IaJOQf&4{!hr&_E`j0)}f1cVt7nMt`eXf3sR2tI`dHbl3Lj1}oVs73_e-UMgoUmNVzem}oG!Kah)L645C9{_4d)+VS72o<!!z2j$^M%9cTe=d3YbMl^}YTa?{^B?w&sl0X#j112E*zqTfunp*S8GDI=;CjS9<G||B',
    'venus.act': 'c-mc%Pe>GD7{*_nasAx=+#PYGNrraR2}d1klrcw~+5y)Zb8~0cHUI0%ZnfzehEh?=W@$*)LC{37@Ss$f1`!0J1O}xP9<?sp#q!X>=n|f`@f!Si_`SUF93BA3pr~wyab_Ro^PHuHyj&uwisII^3%cH57y+-RFB%yb9vXc(`eu3g{p#wM&CPE+J3n@J6Nv;(BnuXz(wgE;w}dFv185S#qZ~9z!7Kwy6|m+<TOn$r!?t}1wnuW}cbL6LIeW7O`%4w^*^>A|MSS7>-co3Pt>y1W|Nd70!NJt8pIz_X`d*Hf-XAQ!6Uv{ul+jq3Y*evz5>X~#o=I8Mt6#o&HuGfs;NZjeud5qt)9WkaE3YP=&ri%v$6mj9FgMZtbfS0cUeCyoF%a<uJL&^9<^6h6x9?c*jo$X|%ids%yY-^WQ**{uA)T!{aauWEc`CQG*jZS>@LcAREXr<oSS_ixw6Q)Ij>6pt44Q=DmPrr>I-#!(q9#ocF{y`e0K#4f8W607pl)yTK${NDnxm--8g&S`A>abP>M%4g)FeZ3coguI+iF#^Rt3GB)XPCHL%NLJGPosMm25(4GH4RkB&3}rwUeNUHdO*u#Hxr?kyMK^)gn*@tO`gGu_BrYN&%?|nTmjwe5B-qETqc<k_A#0K<4c-k7Pbs;wg#85|1R)Ifuj{iAxqaBswY4iA5(NvPj^Nz+%A^mf%^;vxql^F~>(dLvRe{7{r-EV~$1~O|Ud(X~fb5LnDSJ8458JK~spPNE#y=6O@g_h(IJU6t&;JYQK3UeIT5Ey$fIK#64{|(rgPi+PVVP4xhEvYi;tRHPoc}&mpfHK_UUM7`R+@>woMszf*hTc<Qs|@}i}Ej8F!%^9+b3AoK~&K8D<C$SQ;cKn%bI-~@2|cO90^&mZ;~256f3P5cAGT+8?',
    'white.act': 'c-rIV=a-k4*Vos#x3~BA_m7W{&(F`Vudna#@1H+^{`&Rn_wV0-{`~p-_wT=d|NcJ^FpQ#6G<*;MSg!Yg',
}

def get_stock_palette_bytes(name: str) -> bytes:
    """Return the exact 768-byte RGB payload for a bundled stock palette."""
    try:
        encoded = _STOCK_PALETTES_B85[name]
    except KeyError as exc:
        raise KeyError(f"Unknown stock palette: {name}") from exc
    raw = zlib.decompress(base64.b85decode(encoded.encode("ascii")))
    if len(raw) != 768:
        raise ValueError(f"Bundled palette {name!r} decoded to {len(raw)} bytes; expected 768")
    return raw


def get_stock_palette(name: str) -> list[tuple[int, int, int]]:
    """Return a bundled stock palette as 256 RGB tuples."""
    raw = get_stock_palette_bytes(name)
    return [tuple(raw[i:i + 3]) for i in range(0, 768, 3)]
