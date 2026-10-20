public class Demo
{
    String url;
    public void rebuildUrlForConnectionWithLongName(String  hostNamePart,
                                                    int     portNumberPart,
                                                    String  dbNamePart)
    {
        this.url = "jdbc:postgresql://" + hostNamePart + ":" + portNumberPart
            + "/" + dbNamePart;
    }
}
